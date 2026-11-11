"""对话出题接口：会话创建、消息、清除（v2 5.6）。槽位状态存 Redis，快照落库。"""
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.errors import AppError
from app.models import ChatMessage, ChatSession, Document, User
from app.models.base import new_id, utcnow
from app.schemas.api import ChatConfirmBody, ChatMessageBody, ChatSessionCreateBody
from app.schemas.question import Question
from app.services import cache
from app.services.generation import persist_batch
from app.services.model_settings import get_effective_deepseek_key
from app.services.rag import chat_flow, hyde
from app.services.rag.chat_flow import ChatCanceled, build_result_reply, handle_chat, handle_creative
from app.services.rag.data_agent import execute_confirmed, run_data_request
from app.services.rag.intent import detect_intent
from app.services.rag.modes import DEFAULT_MODE, MODES, mode_label
from app.services.rag.qa import answer_question

router = APIRouter(prefix="/api/chat", tags=["chat"])

WELCOME = "你好，我是出题助手。告诉我知识点范围、题型与数量、题目来源和难度，我来为你出题。"


def _slot_key(session_id: str) -> str:
    return cache.PREFIX_CHAT_SESSION.format(session_id=session_id)


def _progress_key(session_id: str) -> str:
    return f"chat:progress:{session_id}"


def _cancel_key(session_id: str) -> str:
    return f"chat:cancel:{session_id}"


def _write_progress(r, session_id: str, percent: int, stage: str) -> None:
    r.hset(_progress_key(session_id), mapping={"percent": int(percent), "stage": stage})
    r.expire(_progress_key(session_id), 1800)


def _is_canceled(r, session_id: str) -> bool:
    return bool(r.exists(_cancel_key(session_id)))


def _get_session(session_id: str, user: User, db: Session) -> ChatSession:
    s = db.get(ChatSession, session_id)
    if s is None or s.user_id != user.id:
        raise AppError("CHAT_SESSION_NOT_FOUND", "对话不存在", status_code=404)
    return s


@router.post("/sessions", status_code=201)
def create_session(
    body: ChatSessionCreateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 校验题库成员与文档状态
    _bank_access_for(db, user, body.bank_id)
    doc = db.get(Document, body.document_id)
    if doc is None or doc.bank_id != body.bank_id:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在或已被删除", status_code=404)
    if doc.status != "ready":
        raise AppError("DOCUMENT_NOT_READY", f"文档尚未完成入库（当前状态 {doc.status}）", status_code=400)

    s = ChatSession(id=new_id("chat"), user_id=user.id, bank_id=body.bank_id, document_id=body.document_id)
    db.add(s)
    db.commit()
    r = cache.get_redis()
    r.hset(_slot_key(s.id), mapping={"slot_state": "{}"})
    r.expire(_slot_key(s.id), settings.chat_session_ttl_seconds)
    return {"session_id": s.id, "bank_id": s.bank_id, "document_id": s.document_id, "welcome": WELCOME}


def _bank_access_for(db: Session, user: User, bank_id: str):
    """非路由上下文里手动构造题库权限（复用 deps 的逻辑）。"""
    from app.deps import BankAccess
    from app.models import Bank, BankMember

    bank = db.get(Bank, bank_id)
    if bank is None or bank.status != "active":
        raise AppError("BANK_NOT_FOUND", "题库不存在或已被删除", status_code=404)
    member = (
        db.query(BankMember)
        .filter(BankMember.bank_id == bank_id, BankMember.user_id == user.id, BankMember.status == "active")
        .one_or_none()
    )
    if member is None:
        raise AppError("BANK_NOT_FOUND", "题库不存在或你不是该题库成员", status_code=404)
    return BankAccess(bank=bank, member=member, user=user, my_role=member.role, my_admin_level=bank.admin_level)


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = _get_session(session_id, user, db)
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == s.id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    return {
        "session_id": s.id,
        "bank_id": s.bank_id,
        "document_id": s.document_id,
        "messages": [
            {"id": m.id, "role": m.role, "text": m.content, "batch_id": m.batch_id, "created_at": m.created_at}
            for m in messages
        ],
    }


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    body: ChatMessageBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发送消息：槽位状态机驱动，齐备后生成题目（含 HyDE + 混合检索）。"""
    s = _get_session(session_id, user, db)
    doc = db.get(Document, s.document_id)
    if doc is None or doc.status != "ready":
        raise AppError("DOCUMENT_NOT_READY", "文档不可用，请重新上传", status_code=400)
    api_key = get_effective_deepseek_key(db, user.id)
    if not api_key:
        raise AppError(
            "DEEPSEEK_KEY_MISSING",
            "尚未配置 DeepSeek API Key，请到个人中心 → 模型配置中填写",
            status_code=400,
        )

    r = cache.get_redis()
    slot_raw = r.hget(_slot_key(s.id), "slot_state")
    slot_state = json.loads(slot_raw) if slot_raw else {}
    if not slot_state and s.slot_state_json:
        slot_state = json.loads(s.slot_state_json)  # Redis 丢失时用数据库快照恢复

    # ---- 模式状态：分段控制器的显式选择优先 ----
    session_mode_raw = r.hget(_slot_key(s.id), "mode")
    has_mode = session_mode_raw in MODES
    session_mode = session_mode_raw if has_mode else DEFAULT_MODE
    # 先读待续需求：切换消息要在清理之前消费它
    pending_message = r.hget(_slot_key(s.id), "pending_message")
    switch_continues = bool(body.switch_only and pending_message)
    mode_changed = body.mode != session_mode
    # 中途显式切换才免守卫；新会话的首条消息仍要做意图校验
    guard_skip = mode_changed and has_mode and not switch_continues
    if mode_changed:
        # 切换模式时旧槽位作废；带待续需求的切换不清理，交给下方接续分支消费
        session_mode = body.mode
        slot_state = {}
        r.hset(_slot_key(s.id), "mode", session_mode)
        if not switch_continues:
            r.hdel(_slot_key(s.id), "pending_message", "pending_images")

    def _base_result(**overrides) -> dict:
        out = {"reply": "", "questions": [], "done": False, "slot_state": slot_state,
               "kind": "reply", "mode": session_mode, "mode_changed": mode_changed}
        out.update(overrides)
        return out

    # 切换确认时若带着被拦下的需求，替换消息内容，在新模式下直接接续执行
    switch_prefix = ""
    if body.switch_only and switch_continues:
        pending_images = json.loads(r.hget(_slot_key(s.id), "pending_images") or "[]")
        body = body.model_copy(update={
            "message": pending_message,
            "images": pending_images if isinstance(pending_images, list) else [],
            "switch_only": False,
        })
        r.hdel(_slot_key(s.id), "pending_message", "pending_images")
        switch_prefix = f"已切换到「{mode_label(session_mode)}」模式，接着处理你刚才的需求。\n\n"
    elif body.switch_only:
        reply = f"已切换到「{mode_label(session_mode)}」模式，请继续。"
        db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="user", content=body.message))
        db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="assistant", content=reply))
        s.slot_state_json = "{}"
        s.last_message_at = utcnow()
        db.commit()
        r.hset(_slot_key(s.id), mapping={"slot_state": "{}"})
        r.expire(_slot_key(s.id), settings.chat_session_ttl_seconds)
        return _base_result(reply=reply, done=True, mode_changed=True)

    # 意图识别：分段控制器负责显式选择，这里只产出建议，不抢控制权
    detected = detect_intent(body.message, session_mode, api_key=api_key)
    if not guard_skip and detected["intent"] != session_mode and detected["confidence"] == "high":
        suggested = detected["intent"]
        # 记下被拦的需求，用户切换模式后自动接续执行
        r.hset(_slot_key(s.id), mapping={
            "pending_message": body.message,
            "pending_images": json.dumps(body.images, ensure_ascii=False),
        })
        r.expire(_slot_key(s.id), settings.chat_session_ttl_seconds)
        reply = (
            f"当前处于「{mode_label(session_mode)}」模式，而你的需求看起来是「{mode_label(suggested)}」"
            f"（{detected.get('reason', '')}）。"
            f"请点击输入框上方的分段控制器切换到「{mode_label(suggested)}」，切换后我会自动接续处理。"
        )
        db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="user", content=body.message))
        db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="assistant", content=reply))
        s.last_message_at = utcnow()
        db.commit()
        return _base_result(reply=reply, kind="mode_mismatch", suggested_template=suggested)
    if (not guard_skip and detected["intent"] != session_mode
            and detected["intent"] in MODES and detected.get("need_confirm")):
        reply = (
            f"你的需求不太确定，可能属于「{mode_label(detected['intent'])}」（{detected.get('reason', '')}）。"
            f"如果是，请点上方分段控制器切换到「{mode_label(detected['intent'])}」；"
            f"否则请补充说明，我会继续按「{mode_label(session_mode)}」模式处理。"
        )
        db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="user", content=body.message))
        db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="assistant", content=reply))
        s.last_message_at = utcnow()
        db.commit()
        return _base_result(reply=reply, kind="mode_confirm", suggested_template=detected["intent"])

    history = [
        {"role": m.role, "text": m.content}
        for m in (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == s.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(6)
            .all()
        )[::-1]
    ]

    # HyDE：scope 未知时先无 HyDE 检索；slot_state 里可能已有 scope
    hyde_text = None
    if slot_state.get("scope"):
        hyde_text = hyde.get_hyde(
            r, s.bank_id, s.document_id, str(slot_state["scope"]), str(slot_state.get("difficulty", "中")), api_key
        )

    r.delete(_cancel_key(s.id))
    _write_progress(r, s.id, 1, "正在准备")

    def _progress(percent: int, stage: str) -> None:
        _write_progress(r, s.id, percent, stage)

    if session_mode == "qa":
        try:
            reply = answer_question(s.bank_id, s.document_id, body.message, history,
                                    api_key=api_key, progress_cb=_progress)
        except chat_flow.ChatCanceled:
            reply = chat_flow.PAUSED_REPLY
        except Exception as exc:  # noqa: BLE001
            from app.services.rag.llm import LLMError, friendly_error

            reply = friendly_error(exc) if isinstance(exc, LLMError) else "答疑服务异常，请稍后再试。"
        result = _base_result(reply=reply, done=True)
    elif session_mode == "data":
        result = _base_result(**run_data_request(db, user, body.message, api_key))
    elif session_mode == "creative":
        try:
            result = _base_result(**handle_creative(
                s.bank_id, s.document_id, doc.name, body.message, history, slot_state,
                existing_stems=body.existing_stems, api_key=api_key, hyde_text=hyde_text,
                images=body.images,
                progress_cb=lambda p, stage: _progress(p, stage),
                cancel_check=lambda: _is_canceled(r, s.id),
            ))
        except ChatCanceled:
            result = _base_result(reply=chat_flow.PAUSED_REPLY)
        except Exception as exc:  # noqa: BLE001
            from app.services.rag.llm import LLMError, friendly_error

            if not isinstance(exc, LLMError):
                raise
            result = _base_result(reply=friendly_error(exc))
    else:
        try:
            result = _base_result(**handle_chat(
                s.bank_id,
                s.document_id,
                doc.name,
                body.message,
                history,
                slot_state,
                existing_stems=body.existing_stems,
                api_key=api_key,
                hyde_text=hyde_text,
                images=body.images,
                progress_cb=lambda p, stage: _progress(p, stage),
                cancel_check=lambda: _is_canceled(r, s.id),
            ))
        except ChatCanceled:
            result = _base_result(reply=chat_flow.PAUSED_REPLY)
        except chat_flow.NeedConfirmError as exc:  # handle_chat 内部已处理，此处兜底
            result = _base_result(
                reply=f"材料中原题不足（{exc.available}/{exc.requested}），请调整数量或来源模式",
            )
        except Exception as exc:  # noqa: BLE001
            # 模型不可用（余额不足、密钥失效、超时）回一条可读消息，不抛 500
            from app.services.rag.llm import LLMError, friendly_error

            if not isinstance(exc, LLMError):
                raise
            result = _base_result(reply=friendly_error(exc))

    if switch_prefix:
        result["reply"] = switch_prefix + (result["reply"] or "")

    # 持久化消息
    db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="user", content=body.message))
    batch_id = None
    if result["questions"]:
        questions = [Question.model_validate(q) for q in result["questions"]]
        from app.services.generation import build_params_from_slots

        params = build_params_from_slots(result["slot_state"], s.bank_id, s.document_id)
        requested = sum(t.count for t in params.types)
        from app.services import question_review

        def review_progress(percent: int, stage: str) -> None:
            if _is_canceled(r, s.id):
                raise ChatCanceled
            # 审核阶段自报 78~98，直接透传，避免长时间停在同一个数字上像卡死
            _write_progress(r, s.id, min(99, max(78, percent)), stage)

        try:
            questions, stats = question_review.review_questions(
                db, user.id, questions, params, doc.name, api_key, hyde_text,
                progress=review_progress,
            )
        except ChatCanceled:
            result["reply"] = chat_flow.PAUSED_REPLY
            result["questions"] = []
            questions, stats = [], None
        if _is_canceled(r, s.id):
            result["reply"] = chat_flow.PAUSED_REPLY
            result["questions"] = []
            questions = []
        if questions:
            _write_progress(r, s.id, 98, "正在写入题目")
            batch = persist_batch(db, user.id, s.bank_id, s.document_id, "chat", params, hyde_text, questions)
            batch_id = batch.id
        result["questions"] = [q.model_dump() for q in questions]
        result["reply"] = build_result_reply(len(questions), requested, stats)
    db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="assistant", content=result["reply"], batch_id=batch_id))
    s.slot_state_json = json.dumps(result["slot_state"], ensure_ascii=False)
    s.last_message_at = utcnow()
    db.commit()

    # Redis 保存最新槽位
    r.hset(_slot_key(s.id), mapping={"slot_state": json.dumps(result["slot_state"], ensure_ascii=False)})
    r.expire(_slot_key(s.id), settings.chat_session_ttl_seconds)
    r.delete(_progress_key(s.id), _cancel_key(s.id))

    return {
        "reply": result["reply"],
        "slot_state": result["slot_state"],
        "questions": result["questions"],
        "done": result["done"],
        "batch_id": batch_id,
        "kind": result.get("kind", "reply"),
        "mode": result.get("mode", session_mode),
        "mode_changed": result.get("mode_changed", mode_changed),
        "suggested_template": result.get("suggested_template"),
        "confirm": result.get("confirm"),
    }


@router.post("/sessions/{session_id}/confirm")
def confirm_operation(
    session_id: str,
    body: ChatConfirmBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """数据管理高危操作确认：接受执行，拒绝取消。"""
    s = _get_session(session_id, user, db)
    reply = execute_confirmed(db, user, body.confirm_id, body.accepted)
    db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="user",
                       content="接受操作" if body.accepted else "拒绝操作"))
    db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="assistant", content=reply))
    s.last_message_at = utcnow()
    db.commit()
    return {"reply": reply, "done": True}


@router.get("/sessions/{session_id}/progress")
def read_generation_progress(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """对话生成的实时阶段，供前端在等待时轮询。"""
    s = _get_session(session_id, user, db)
    data = cache.get_redis().hgetall(_progress_key(s.id))
    if not data:
        return {"active": False, "percent": 0, "stage": ""}
    return {
        "active": True,
        "percent": int(data.get("percent") or 0),
        "stage": data.get("stage") or "",
    }


@router.post("/sessions/{session_id}/cancel", status_code=202)
def cancel_generation(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """请求暂停：后台在下一个检查点停下，并且不写入题目预览。"""
    s = _get_session(session_id, user, db)
    r = cache.get_redis()
    r.set(_cancel_key(s.id), "1", ex=900)
    _write_progress(r, s.id, 0, "已收到暂停请求")
    return {"canceled": True}


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = _get_session(session_id, user, db)
    db.query(ChatMessage).filter(ChatMessage.session_id == s.id).delete()
    db.delete(s)
    db.commit()
    cache.get_redis().delete(_slot_key(s.id))
    return None

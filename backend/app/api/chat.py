"""对话出题：SQL 保存完整会话与运行状态，取消和最终提交按 run_id 隔离。"""
import json
from dataclasses import dataclass

from fastapi import APIRouter, Depends
from redis.exceptions import RedisError
from sqlalchemy import or_, update
from sqlalchemy.orm import Query, Session

from app.db import SessionLocal, get_db
from app.deps import get_current_user, resolve_bank_access
from app.errors import AppError
from app.models import ChatMessage, ChatSession, Document, User
from app.models.base import new_id, utcnow
from app.schemas.api import ChatConfirmBody, ChatMessageBody, ChatSessionCreateBody
from app.schemas.question import GenerateParams, Question
from app.services import auth, cache, generation, question_review, rag_settings
from app.services.phoenix_tracing import trace_run
from app.services.generation import persist_batch
from app.services.model_settings import get_effective_deepseek_key
from app.services.rag import chat_flow
from app.services.rag.chat_flow import ChatCanceled, build_result_reply
from app.services.rag.data_agent import execute_confirmed
from app.services.rag.intent import detect_intent
from app.services.rag.llm import LLMError, friendly_error
from app.services.rag.modes import DEFAULT_MODE, MODES, mode_label
from app.services.rag.skills import ChatContext, get_skill

router = APIRouter(prefix="/api/chat", tags=["chat"])
WELCOME = "你好，我是出题助手。告诉我知识点范围、题型与数量、题目来源和难度，我来为你出题。"


@dataclass
class _TurnState:
    """本轮工作副本；仅成功提交时发布到 SQL 会话。"""

    slots: dict
    mode: str
    pending_message: str | None
    pending_images: list[str]
    auth_version: int


def _slot_key(session_id: str) -> str:
    return cache.PREFIX_CHAT_SESSION.format(session_id=session_id)


def _progress_key(session_id: str) -> str:
    return f"chat:progress:{session_id}"


def _get_session(session_id: str, user: User, db: Session) -> ChatSession:
    s = db.get(ChatSession, session_id, populate_existing=True)
    if s is None or s.user_id != user.id:
        raise AppError("CHAT_SESSION_NOT_FOUND", "对话不存在", status_code=404)
    return s


def _current_run(db: Session, session_id: str, run_id: str) -> Query[ChatSession]:
    return db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.run_id == run_id,
        ChatSession.run_status == "running",
        or_(ChatSession.canceled_run_id.is_(None), ChatSession.canceled_run_id != run_id),
    )


def _is_canceled(session_id: str, run_id: str) -> bool:
    """每次读取独立 SQL 快照，旧 run 永远不能因新 run 开始而恢复有效。"""
    with SessionLocal() as db:
        return _current_run(db, session_id, run_id).first() is None


def _write_progress(session_id: str, run_id: str, percent: int, stage: str) -> None:
    """进度先提交 SQL，Redis 失败不影响出题或取消。"""
    with SessionLocal() as db:
        changed = _current_run(db, session_id, run_id).update({
            "run_progress": min(99, max(0, percent)), "run_stage": stage,
        }, synchronize_session=False)
        db.commit()
        if not changed:
            raise ChatCanceled
    try:
        r = cache.get_redis()
        r.hset(_progress_key(session_id), mapping={
            "run_id": run_id, "percent": int(percent), "stage": stage,
        })
        r.expire(_progress_key(session_id), 1800)
    except RedisError:
        pass  # SQL 已保存，轮询只读取 SQL。


def _begin_run(
    db: Session, session_id: str, user_id: str, *, auth_version: int | None = None,
) -> ChatSession:
    """短事务串行化开始/取消/最终提交；提交后才允许执行模型。"""
    if auth_version is None:
        user = db.get(User, user_id)
        auth_version = user.auth_version if user else -1
    db.rollback()
    auth.assert_version(db, user_id, auth_version)
    db.execute(update(ChatSession).where(
        ChatSession.id == session_id, ChatSession.user_id == user_id,
    ).values(run_status=ChatSession.run_status))
    s = db.get(ChatSession, session_id, populate_existing=True)
    if s is None or s.user_id != user_id:
        raise AppError("CHAT_SESSION_NOT_FOUND", "对话不存在", 404)
    if s.run_status == "running":
        db.rollback()
        raise AppError("CHAT_BUSY", "本对话已有进行中的请求，请等待完成或暂停后重试", 409)
    generation.validate_resources(db, user_id, s.bank_id, s.document_id)
    s.run_id = new_id("run")
    s.run_status = "running"
    s.run_progress = 0
    s.run_stage = "正在准备"
    # canceled_run_id 保留旧运行的取消事实，绝不在开始新运行时清空。
    db.commit()
    return s


def _end_failed_run(session_id: str, run_id: str) -> None:
    """异常收尾只影响自己的 run；已取消或已被后继替换的运行保持原样。"""
    with SessionLocal() as db:
        _current_run(db, session_id, run_id).update({
            "run_status": "failed", "run_stage": "请求未完成，请重试",
        }, synchronize_session=False)
        db.commit()


def _paused_result(db: Session, session_id: str) -> dict:
    db.rollback()
    s = db.get(ChatSession, session_id, populate_existing=True)
    return {
        "reply": chat_flow.PAUSED_REPLY, "questions": [], "done": False, "batch_id": None,
        "slot_state": json.loads(s.slot_state_json or "{}") if s else {},
        "kind": "reply", "mode": (s.mode or DEFAULT_MODE) if s else DEFAULT_MODE,
        "mode_changed": False, "suggested_template": None, "confirm": None,
    }


@router.post("/sessions", status_code=201)
def create_session(
    body: ChatSessionCreateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    generation.validate_resources(db, user.id, body.bank_id, body.document_id)
    s = ChatSession(
        id=new_id("chat"), user_id=user.id, bank_id=body.bank_id,
        document_id=body.document_id, slot_state_json="{}",
    )
    db.add(s)
    db.commit()
    return {"session_id": s.id, "bank_id": s.bank_id, "document_id": s.document_id,
            "welcome": WELCOME}


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = _get_session(session_id, user, db)
    resolve_bank_access(db, user, s.bank_id)
    messages = db.query(ChatMessage).filter(ChatMessage.session_id == s.id).order_by(
        ChatMessage.created_at,
    ).all()
    return {
        "session_id": s.id, "bank_id": s.bank_id, "document_id": s.document_id,
        "messages": [
            {"id": m.id, "role": m.role, "text": m.content, "batch_id": m.batch_id,
             "created_at": m.created_at} for m in messages
        ],
    }


@router.post("/sessions/{session_id}/messages")
@trace_run("conversation")
def send_message(
    session_id: str,
    body: ChatMessageBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """运行状态先提交，题目、两条消息与完整会话状态最后一次提交。"""
    user_id, auth_version = user.id, user.auth_version
    s = _get_session(session_id, user, db)
    generation.validate_resources(db, user.id, s.bank_id, s.document_id)
    api_key = get_effective_deepseek_key(db, user.id)
    if not api_key:
        raise AppError("DEEPSEEK_KEY_MISSING", "尚未配置 DeepSeek API Key，请到设置 → 模型与服务中填写", 400)
    # 升级前待续内容仅在 Redis 中；切换不能被静默当作已经接续。
    interrupted_stage = s.run_stage if s.run_status == "interrupted" else ""
    s = _begin_run(db, session_id, user_id, auth_version=auth_version)
    run_id = s.run_id
    assert run_id is not None
    try:
        return _run_message(db, user, s, body, api_key, run_id,
                            interrupted_stage=interrupted_stage)
    except ChatCanceled:
        return _paused_result(db, session_id)
    finally:
        # 回滚工作 Session 的读快照/失败写事务，随后才用独立短事务收尾。
        db.rollback()
        _end_failed_run(session_id, run_id)


def _run_message(
    db: Session, user: User, s: ChatSession, body: ChatMessageBody, api_key: str, run_id: str,
    *, interrupted_stage: str = "",
) -> dict:
    session_id, user_id, bank_id, document_id = s.id, user.id, s.bank_id, s.document_id
    doc = db.get(Document, document_id)
    if doc is None:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在或已被删除", 404)
    doc_name = doc.name
    state = _TurnState(
        slots=json.loads(s.slot_state_json or "{}"), mode=s.mode or DEFAULT_MODE,
        pending_message=s.pending_message,
        pending_images=json.loads(s.pending_images_json or "[]"),
        auth_version=user.auth_version,
    )
    has_mode = s.mode in MODES
    pending_message = state.pending_message if body.switch_only else None
    if not body.switch_only:
        state.pending_message, state.pending_images = None, []
    switch_continues = body.switch_only and pending_message is not None
    mode_changed = body.mode != state.mode
    guard_skip = mode_changed and has_mode and not switch_continues
    if mode_changed:
        state.mode, state.slots = body.mode, {}
        if not switch_continues:
            state.pending_message, state.pending_images = None, []

    def base_result(**overrides) -> dict:
        out = {"reply": "", "questions": [], "done": False, "slot_state": state.slots,
               "kind": "reply", "mode": state.mode, "mode_changed": mode_changed}
        out.update(overrides)
        return out

    # 技能只消费已加载的标量快照；脱离 Session 后 rollback 不会使属性访问重新借连接。
    # 运行状态在 _begin_run 中已提交，本段尚未添加业务写入。
    db.expunge(s)
    db.expunge(user)
    db.rollback()
    switch_prefix = ""
    if body.switch_only and switch_continues:
        body = body.model_copy(update={
            "message": pending_message, "images": state.pending_images, "switch_only": False,
        })
        state.pending_message, state.pending_images = None, []
        switch_prefix = f"已切换到「{mode_label(state.mode)}」模式，接着处理你刚才的需求。\n\n"
    elif body.switch_only:
        state.slots = {}
        result = base_result(
            reply=(f"已切换到「{mode_label(state.mode)}」模式。"
                   + (f"{interrupted_stage}；请重新发送需求文字和图片。"
                      if interrupted_stage else "请继续。")),
            done=True, mode_changed=True,
        )
        return _commit_turn(db, session_id, user_id, bank_id, document_id, run_id, body,
                            state, result)

    _write_progress(session_id, run_id, 1, "正在准备")
    detected = detect_intent(body.message, state.mode, api_key=api_key)
    if not guard_skip and detected["intent"] != state.mode and detected["confidence"] == "high":
        suggested = detected["intent"]
        state.pending_message, state.pending_images = body.message, list(body.images)
        result = base_result(
            reply=(f"当前处于「{mode_label(state.mode)}」模式，而你的需求看起来是「{mode_label(suggested)}」"
                   f"（{detected.get('reason', '')}）。请点击输入框上方的分段控制器切换到"
                   f"「{mode_label(suggested)}」，切换后我会自动接续处理。"),
            kind="mode_mismatch", suggested_template=suggested,
        )
        return _commit_turn(db, session_id, user_id, bank_id, document_id, run_id, body,
                            state, result)
    if (not guard_skip and detected["intent"] != state.mode
            and detected["intent"] in MODES and detected.get("need_confirm")):
        result = base_result(
            reply=(f"你的需求不太确定，可能属于「{mode_label(detected['intent'])}」"
                   f"（{detected.get('reason', '')}）。如果是，请点上方分段控制器切换到"
                   f"「{mode_label(detected['intent'])}」；否则请补充说明，"
                   f"我会继续按「{mode_label(state.mode)}」模式处理。"),
            kind="mode_confirm", suggested_template=detected["intent"],
        )
        return _commit_turn(db, session_id, user_id, bank_id, document_id, run_id, body,
                            state, result)

    history = [
        {"role": m.role, "text": m.content}
        for m in db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(
            ChatMessage.created_at.desc(),
        ).limit(6).all()[::-1]
    ]
    db.rollback()
    hyde_text = None
    if state.slots.get("scope"):
        hyde_text = generation.get_cached_hyde(
            bank_id, document_id, str(state.slots["scope"]),
            str(state.slots.get("difficulty", "中")), api_key,
        )
    def progress(percent: int, stage: str) -> None:
        _write_progress(session_id, run_id, percent, stage)
    ctx = ChatContext(
        db=db, user=user, session=s, doc_name=doc_name, message=body.message,
        history=history, slot_state=state.slots, existing_stems=body.existing_stems,
        api_key=api_key, hyde_text=hyde_text, images=body.images,
        progress_cb=progress, cancel_check=lambda: _is_canceled(session_id, run_id),
    )
    try:
        result = base_result(**get_skill(state.mode).run(ctx))
    except chat_flow.NeedConfirmError as exc:
        result = base_result(reply=f"材料中原题不足（{exc.available}/{exc.requested}），请调整数量或来源模式")
    except LLMError as exc:
        result = base_result(reply=friendly_error(exc))
    if switch_prefix:
        result["reply"] = switch_prefix + (result["reply"] or "")
    questions: list[Question] = []
    params = None
    if result["questions"]:
        questions = [Question.model_validate(q) for q in result["questions"]]
        params = generation.build_params_from_slots(result["slot_state"], bank_id, document_id)
        requested = sum(t.count for t in params.types)

        def review_progress(percent: int, stage: str) -> None:
            _write_progress(session_id, run_id, min(99, max(78, percent)), stage)

        if _is_canceled(session_id, run_id):
            raise ChatCanceled
        # 审核自行短事务物化语料；调用时没有活动事务、待写消息/槽位或资料门禁。
        questions, stats = question_review.review_questions(
            db, user_id, questions, params, doc_name, api_key, hyde_text, progress=review_progress,
        )
        result["questions"] = [q.model_dump() for q in questions]
        result["reply"] = build_result_reply(len(questions), requested, stats)
    return _commit_turn(db, session_id, user_id, bank_id, document_id, run_id, body,
                        state, result, params=params, hyde_text=hyde_text, questions=questions)


def _commit_turn(
    db: Session, session_id: str, user_id: str, bank_id: str, document_id: str,
    run_id: str, body: ChatMessageBody, state: _TurnState, result: dict, *,
    params: GenerateParams | None = None, hyde_text: str | None = None,
    questions: list[Question] | None = None,
) -> dict:
    """所有模型已完成后，锁内重新验证 run 和资源，单次提交整轮结果。"""
    db.rollback()
    auth.assert_version(db, user_id, state.auth_version)
    rag_settings.assert_mutations_allowed(db)
    changed = _current_run(db, session_id, run_id).filter(ChatSession.user_id == user_id).update(
        {"run_stage": "正在保存"}, synchronize_session=False,
    )
    if not changed:
        raise ChatCanceled
    s = db.get(ChatSession, session_id, populate_existing=True)
    if s is None or s.bank_id != bank_id or s.document_id != document_id:
        raise ChatCanceled
    generation.validate_resources(db, user_id, bank_id, document_id)
    batch_id = None
    if questions and params is not None:
        batch_id = persist_batch(
            db, user_id, bank_id, document_id, "chat", params, hyde_text, questions, commit=False,
        ).id
    db.add(ChatMessage(id=new_id("msg"), session_id=session_id, role="user", content=body.message))
    db.add(ChatMessage(id=new_id("msg"), session_id=session_id, role="assistant",
                       content=result["reply"], batch_id=batch_id))
    s.slot_state_json = json.dumps(result["slot_state"], ensure_ascii=False)
    s.mode = state.mode
    s.pending_message = state.pending_message
    s.pending_images_json = json.dumps(state.pending_images, ensure_ascii=False)
    s.last_message_at = utcnow()
    s.run_status, s.run_progress, s.run_stage = "done", 100, ""
    db.commit()
    return {
        "reply": result["reply"], "slot_state": result["slot_state"],
        "questions": result["questions"], "done": result["done"], "batch_id": batch_id,
        "kind": result.get("kind", "reply"), "mode": state.mode,
        "mode_changed": result.get("mode_changed", False),
        "suggested_template": result.get("suggested_template"), "confirm": result.get("confirm"),
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
    resolve_bank_access(db, user, s.bank_id)
    reply = execute_confirmed(db, user, body.confirm_id, body.accepted, session_id=s.id)
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
    """SQL 进度在 Redis 丢失、过期或不可用时仍可完整读取。"""
    s = _get_session(session_id, user, db)
    resolve_bank_access(db, user, s.bank_id)
    active = s.run_status == "running"
    return {"active": active, "percent": s.run_progress if active else 0,
            "stage": s.run_stage if active or s.run_status == "interrupted" else ""}


@router.post("/sessions/{session_id}/cancel", status_code=202)
def cancel_generation(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """原子绑定当前运行的取消事实；与开始和最终提交使用同一 SQL 行锁。"""
    s = _get_session(session_id, user, db)
    target_run_id = s.run_id
    user_id = user.id
    db.rollback()
    db.execute(update(ChatSession).where(
        ChatSession.id == session_id, ChatSession.user_id == user_id,
        ChatSession.run_status == "running", ChatSession.run_id == target_run_id,
    ).values(canceled_run_id=target_run_id, run_status="canceled",
             run_progress=0, run_stage="已收到暂停请求"))
    db.commit()
    return {"canceled": True}


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_session(session_id, user, db)
    user_id = user.id
    db.rollback()
    db.execute(update(ChatSession).where(
        ChatSession.id == session_id, ChatSession.user_id == user_id,
    ).values(run_status="canceled"))
    s = _get_session(session_id, user, db)
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(s)
    db.commit()
    try:
        cache.get_redis().delete(_slot_key(session_id), _progress_key(session_id))
    except RedisError:
        pass
    return None

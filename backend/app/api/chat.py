"""对话出题接口：会话创建、消息、清除（v2 5.6）。槽位状态存 Redis，快照落库。"""
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user, resolve_bank_access
from app.errors import AppError
from app.models import ChatMessage, ChatSession, Document, User
from app.models.base import new_id, utcnow
from app.schemas.api import ChatMessageBody, ChatSessionCreateBody
from app.schemas.question import Question
from app.services import cache
from app.services.generation import persist_batch
from app.services.model_settings import get_effective_deepseek_key
from app.services.rag import chat_flow, hyde
from app.services.rag.chat_flow import handle_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])

WELCOME = "你好，我是出题助手。告诉我知识点范围、题型与数量、题目来源和难度，我来为你出题。"


def _slot_key(session_id: str) -> str:
    return cache.PREFIX_CHAT_SESSION.format(session_id=session_id)


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
    resolve_bank_access(db, user, body.bank_id)
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


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = _get_session(session_id, user, db)
    resolve_bank_access(db, user, s.bank_id)
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
    resolve_bank_access(db, user, s.bank_id)
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

    try:
        result = handle_chat(
            s.bank_id,
            s.document_id,
            doc.name,
            body.message,
            history,
            slot_state,
            existing_stems=body.existing_stems,
            api_key=api_key,
            hyde_text=hyde_text,
        )
    except chat_flow.NeedConfirmError as exc:  # handle_chat 内部已处理，此处兜底
        result = {
            "reply": f"材料中原题不足（{exc.available}/{exc.requested}），请调整数量或来源模式",
            "slot_state": slot_state,
            "questions": [],
            "done": False,
        }

    # 持久化消息
    db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="user", content=body.message))
    batch_id = None
    if result["questions"]:
        questions = [Question.model_validate(q) for q in result["questions"]]
        from app.services.generation import build_params_from_slots

        params = build_params_from_slots(result["slot_state"], s.bank_id, s.document_id)
        batch = persist_batch(db, user.id, s.bank_id, s.document_id, "chat", params, hyde_text, questions)
        batch_id = batch.id
    db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="assistant", content=result["reply"], batch_id=batch_id))
    s.slot_state_json = json.dumps(result["slot_state"], ensure_ascii=False)
    s.last_message_at = utcnow()
    db.commit()

    # Redis 保存最新槽位
    r.hset(_slot_key(s.id), mapping={"slot_state": json.dumps(result["slot_state"], ensure_ascii=False)})
    r.expire(_slot_key(s.id), settings.chat_session_ttl_seconds)

    return {
        "reply": result["reply"],
        "slot_state": result["slot_state"],
        "questions": result["questions"],
        "done": result["done"],
        "batch_id": batch_id,
    }


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

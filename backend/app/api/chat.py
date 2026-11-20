"""对话出题：SQL 保存完整会话与运行状态，取消和最终提交按 run_id 隔离。"""
import json
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends
from redis.exceptions import RedisError
from sqlalchemy import case, or_, select, update
from sqlalchemy.orm import Query, Session

from app.db import SessionLocal, get_db
from app.deps import get_current_user, resolve_bank_access
from app.errors import AppError
from app.models import Bank, ChatMessage, ChatRequest, ChatSession, Document, Favorite, OpsRun, User
from app.models.base import new_id, utcnow
from app.models.ops_run import RunEntrypoint, RunErrorCode, RunStatus
from app.models.question import Question as SavedQuestion
from app.schemas.api import (
    ChatConfirmBody, ChatMessageBody, ChatMessageResponse, ChatRequestResponse,
    ChatSavedQuestion, ChatSessionCreateBody, ChatSessionDetailResponse,
)
from app.schemas.auth import ErrorResponse
from app.schemas.question import GenerateParams, Question
from app.services import auth, cache, generation, question_review, rag_settings
from app.services.generation import persist_batch
from app.services.generation_cancellation import run_checked
from app.services.generation_lifecycle import (
    GenerationRun, conversation_turn, error_code, rollback_business,
)
from app.services.model_settings import get_effective_deepseek_key
from app.services.ops_runs import RunConflictError
from app.services.phoenix_tracing import current_run_id, trace_run
from app.services.rag import chat_flow, question_gen
from app.services.rag.chat_flow import ChatCanceled, build_result_reply
from app.services.rag.data_agent import execute_confirmed
from app.services.rag.intent import detect_intent
from app.services.rag.llm import LLMError, friendly_error
from app.services.rag.memory import answer_casually, build_short_term_history
from app.services.rag.modes import DEFAULT_MODE, MODES, mode_label
from app.services.rag.prompts import CREATIVE_SYSTEM_EXTRA
from app.services.rag.question_gen import TYPE_LABELS
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


@router.get("/sessions")
def list_sessions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict[str, list[dict]]:
    """仅列出当前账号仍有资料访问权的最近会话。"""
    rows = db.query(ChatSession).filter(ChatSession.user_id == user.id).order_by(
        ChatSession.last_message_at.desc(), ChatSession.id,
    ).limit(100).all()
    items = []
    for session in rows:
        try:
            generation.validate_resources(db, user.id, session.bank_id, session.document_id)
        except AppError as exc:
            if exc.status_code in (403, 404, 409) or exc.code == "DOCUMENT_NOT_READY":
                continue
            raise
        first = db.query(ChatMessage).filter(
            ChatMessage.session_id == session.id, ChatMessage.role == "user",
        ).order_by(ChatMessage.created_at, ChatMessage.id).first()
        doc = db.get(Document, session.document_id)
        title = (first.content if first else "").strip().replace("\n", " ")[:24]
        items.append({
            "session_id": session.id, "title": title or (doc.name if doc else "未命名对话"),
            "bank_id": session.bank_id, "document_id": session.document_id,
            "document_name": doc.name if doc else None,
            "last_message_at": session.last_message_at, "created_at": session.created_at,
        })
    return {"items": items}


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
    request_id: str | None = None,
) -> ChatSession | ChatRequest:
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
    if request_id is not None:
        previous = db.get(ChatRequest, (session_id, request_id), populate_existing=True)
        if previous is not None:
            db.commit()
            return previous
    unfinished = db.scalar(select(ChatRequest.request_id).where(
        ChatRequest.session_id == session_id, ChatRequest.execution_finished_at.is_(None),
    ).limit(1))
    if s.run_status == "running" or unfinished is not None:
        db.rollback()
        raise AppError("CHAT_BUSY", "本对话已有进行中的请求，请等待完成或暂停后重试", 409)
    if request_id is None:
        generation.validate_resources(db, user_id, s.bank_id, s.document_id)
    trace_id = current_run_id()
    # 被嵌套请求继承的追踪上下文可能属于旧运行，不能复用其取消标识或台账主键。
    if trace_id and (trace_id in {s.run_id, s.canceled_run_id} or db.get(OpsRun, trace_id)
                     or db.scalar(select(ChatRequest.request_id).where(
                         ChatRequest.run_id == trace_id,
                     ))):
        trace_id = None
    s.run_id = trace_id or new_id("run")
    s.run_status = "running"
    s.run_progress = 0
    s.run_stage = "正在准备"
    if request_id is not None:
        db.add(ChatRequest(
            session_id=session_id, request_id=request_id, run_id=s.run_id, status="running",
        ))
    db.commit()
    return s


def _transition_chat_ledger(
    db: Session, session_id: str, user_id: str, run_id: str, status: RunStatus,
    *, code: RunErrorCode | None = None,
) -> None:
    """在会话事务中写入开始或无批次失败，保留台账的并发比较。"""
    row = db.get(OpsRun, run_id, populate_existing=True)
    if (row is None or row.entrypoint != RunEntrypoint.CONVERSATION
            or row.owner_user_id != user_id or row.session_id != session_id):
        raise RunConflictError("运行与会话或账号不一致")
    if status == RunStatus.RUNNING and row.status == RunStatus.RUNNING:
        return
    if status == RunStatus.RUNNING:
        allowed = {RunStatus.ACCEPTED, RunStatus.UNKNOWN}
    elif status == RunStatus.FAILED and code is not None:
        allowed = {RunStatus.ACCEPTED, RunStatus.RUNNING, RunStatus.UNKNOWN}
    else:
        raise ValueError("不支持的会话运行状态")
    if row.status not in allowed:
        raise RunConflictError("已确认停止的运行不能再次变更")
    observed_at = max(utcnow(), row.last_observed_at)
    values: dict[str, object] = {"status": status.value, "last_observed_at": observed_at}
    if status == RunStatus.RUNNING:
        values.update(started_at=row.started_at or observed_at, error_code=None)
    else:
        assert code is not None
        values.update(finished_at=observed_at, delivered_count=0, error_code=code.value)
    changed = db.execute(update(OpsRun).where(
        OpsRun.run_id == run_id, OpsRun.owner_user_id == user_id,
        OpsRun.session_id == session_id, OpsRun.status == row.status,
        OpsRun.last_observed_at == row.last_observed_at,
        # 状态和时间可能回到旧值，仍须核对其余可变事实。
        OpsRun.started_at.is_not_distinct_from(row.started_at),
        OpsRun.finished_at.is_not_distinct_from(row.finished_at),
        OpsRun.batch_id.is_not_distinct_from(row.batch_id),
        OpsRun.delivered_count.is_not_distinct_from(row.delivered_count),
        OpsRun.error_code.is_not_distinct_from(row.error_code),
    ).values(**values).returning(OpsRun.run_id).execution_options(synchronize_session=False))
    if changed.scalar_one_or_none() is None:
        raise RunConflictError("运行观察发生并发冲突，请回滚后重新读取")


def _begin_generation(
    session_id: str, user_id: str, run_id: str, run: GenerationRun, params: GenerateParams,
) -> None:
    """受理和开始分别持久化，均与删除、取消按会话行串行化。"""
    with SessionLocal() as db:
        changed = _current_run(db, session_id, run_id).filter(ChatSession.user_id == user_id).update(
            {"run_status": ChatSession.run_status}, synchronize_session=False,
        )
        if not changed:
            raise ChatCanceled
        run.run_id = run_id
        run.accept(params, db=db)
        db.commit()
    run.register_accepted()
    with SessionLocal() as db:
        changed = _current_run(db, session_id, run_id).filter(ChatSession.user_id == user_id).update(
            {"run_status": ChatSession.run_status}, synchronize_session=False,
        )
        if not changed:
            raise ChatCanceled
        _transition_chat_ledger(db, session_id, user_id, run_id, RunStatus.RUNNING)
        db.commit()


def _end_failed_run(session_id: str, run_id: str) -> None:
    """工作事务和执行权释放后，记录该运行的退出及未发布结果的终态。"""
    with SessionLocal() as db:
        changed = _current_run(db, session_id, run_id).update({
            "run_status": "failed", "run_stage": "请求未完成，请重试",
        }, synchronize_session=False)
        request = db.scalar(select(ChatRequest).where(ChatRequest.run_id == run_id))
        if request is not None:
            if request.status == "running":
                request.status = "failed" if changed else "canceled"
            request.execution_finished_at = utcnow()
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


def _saved_questions(
    db: Session, s: ChatSession, batch_id: str,
) -> list[ChatSavedQuestion]:
    rows = db.execute(
        select(SavedQuestion, Document.name, Favorite)
        .select_from(SavedQuestion)
        .join(Bank, Bank.id == SavedQuestion.bank_id)
        .join(Document, (Document.id == SavedQuestion.document_id)
              & (Document.bank_id == Bank.id))
        .outerjoin(Favorite, (Favorite.question_id == SavedQuestion.id)
                   & (Favorite.user_id == s.user_id))
        .where(
            SavedQuestion.batch_id == batch_id, SavedQuestion.created_by == s.user_id,
            SavedQuestion.bank_id == s.bank_id, SavedQuestion.document_id == s.document_id,
            Bank.status == "active", Document.status != "deleting",
        )
        .order_by(SavedQuestion.created_at, SavedQuestion.id)
    )
    return [
        ChatSavedQuestion.model_validate(generation.question_to_api(
            question, starred=favorite is not None,
            favorite_group_id=favorite.group_id if favorite is not None else None,
            doc_name=doc_name,
        ))
        for question, doc_name, favorite in rows
    ]


def _request_response(
    db: Session, s: ChatSession, user: User, request: ChatRequest,
) -> ChatRequestResponse:
    result = (
        ChatMessageResponse.model_validate_json(request.result_json)
        if request.result_json is not None else None
    )
    if result is not None:
        resolve_bank_access(db, user, s.bank_id)
        if request.batch_id is not None:
            result.questions = list(_saved_questions(db, s, request.batch_id))
    return ChatRequestResponse(
        status=request.status, execution_finished=request.execution_finished_at is not None,
        batch_id=request.batch_id, result=result,
    )


def _replay_request(
    db: Session, s: ChatSession, user: User, request: ChatRequest,
) -> ChatMessageResponse:
    if request.status == "canceled":
        return ChatMessageResponse.model_validate(_paused_result(db, s.id))
    if request.status == "done":
        result = _request_response(db, s, user, request).result
        assert result is not None
        return result
    if request.status == "running":
        raise AppError("CHAT_BUSY", "本轮请求正在处理，请查询处理状态", 409)
    raise AppError("CHAT_REQUEST_FINISHED", "本轮请求已结束，请使用新的请求标识重试", 409)


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


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
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
        "mode": s.mode or DEFAULT_MODE,
        "messages": [
            {"id": m.id, "role": m.role, "text": m.content, "batch_id": m.batch_id,
             "created_at": m.created_at} for m in messages
        ],
    }


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse, responses={
    409: {"model": ErrorResponse, "description": "当前会话正在处理消息，请稍后再试"},
})
@trace_run("conversation", force_new=True)
def send_message(
    session_id: str,
    body: ChatMessageBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatMessageResponse:
    """运行状态先提交，题目、两条消息与完整会话状态最后一次提交。"""
    user_id, auth_version = user.id, user.auth_version
    s = _get_session(session_id, user, db)
    request_id = str(body.request_id) if body.request_id is not None else None
    if request_id is not None:
        previous = db.get(ChatRequest, (session_id, request_id))
        if previous is not None:
            return _replay_request(db, s, user, previous)
    run_id = None
    try:
        with conversation_turn(session_id):
            api_key = _message_api_key(db, s, user_id) if request_id is None else None
            interrupted_stage = s.run_stage if s.run_status == "interrupted" else ""
            claim = _begin_run(
                db, session_id, user_id, auth_version=auth_version, request_id=request_id,
            )
            if isinstance(claim, ChatRequest):
                return _replay_request(db, s, user, claim)
            run_id = claim.run_id
            assert run_id is not None
            return _send_message(
                session_id, body, user, db, claim, user_id, run_id, interrupted_stage, api_key,
            )
    finally:
        if run_id is not None:
            db.rollback()
            _end_failed_run(session_id, run_id)


def _message_api_key(db: Session, s: ChatSession, user_id: str) -> str:
    generation.validate_resources(db, user_id, s.bank_id, s.document_id)
    api_key = get_effective_deepseek_key(db, user_id)
    if not api_key:
        raise AppError(
            "DEEPSEEK_KEY_MISSING", "尚未配置 DeepSeek API Key，请到个人中心 → API 配置中填写", 400,
        )
    return api_key


def _send_message(
    session_id: str, body: ChatMessageBody, user: User, db: Session, s: ChatSession,
    user_id: str, run_id: str, interrupted_stage: str, api_key: str | None,
) -> ChatMessageResponse:
    """持有会话执行权直至当前消息确认停止或完成。"""
    run = GenerationRun(
        RunEntrypoint.CONVERSATION, user_id, s.bank_id, s.document_id, session_id=session_id,
    )
    with run.observe(db):
        try:
            if _is_canceled(session_id, run_id):
                raise ChatCanceled
            if api_key is None:
                api_key = _message_api_key(db, s, user_id)
            return _run_message(db, user, s, body, api_key, run_id, run=run,
                                interrupted_stage=interrupted_stage)
        except ChatCanceled:
            db.rollback()
            try:
                run.cancel()
            except RunConflictError:
                # 删除会话可能刚将旧快照改为 unknown；重读后确认取消。
                run.cancel()
            return ChatMessageResponse.model_validate(_paused_result(db, session_id))


def _run_message(
    db: Session, user: User, s: ChatSession, body: ChatMessageBody, api_key: str, run_id: str,
    *, run: GenerationRun, interrupted_stage: str = "",
) -> ChatMessageResponse:
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
               "kind": "reply", "mode": state.mode, "mode_changed": mode_changed,
               "confirm": None, "batch_id": None}
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

    def check_canceled() -> None:
        if _is_canceled(session_id, run_id):
            raise ChatCanceled

    _write_progress(session_id, run_id, 1, "正在准备")
    detected = run_checked(
        check_canceled, detect_intent, body.message, state.mode,
        api_key=api_key, cancel_check=check_canceled,
    )
    if (not guard_skip and detected["intent"] != state.mode
            and detected["intent"] in MODES and detected["confidence"] == "high"):
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

    history = build_short_term_history([
        {"role": m.role, "text": m.content}
        for m in db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(
            ChatMessage.created_at.desc(),
        ).limit(12).all()[::-1]
    ])
    db.rollback()
    hyde_text = None
    if (detected.get("intent") == "smalltalk" or (
        detected.get("intent") == "unknown" and detected.get("confidence") in ("low", "mid")
    )):
        reply = run_checked(
            check_canceled, answer_casually, state.mode, doc_name, history, body.message,
            api_key, cancel_check=check_canceled,
        )
        return _commit_turn(
            db, session_id, user_id, bank_id, document_id, run_id, body, state,
            base_result(reply=switch_prefix + reply, done=True), run=run,
        )

    last_progress = 0

    def progress(percent: int, stage: str) -> None:
        nonlocal last_progress
        last_progress = max(last_progress, min(99, max(0, percent)))
        _write_progress(session_id, run_id, last_progress, stage)

    generation_params: GenerateParams | None = None

    def begin_generation(params: GenerateParams) -> None:
        nonlocal generation_params
        generation_params = params
        # 会话的每轮消息有 run_id，台账只在真正决定出题时受理。
        _begin_generation(session_id, user_id, run_id, run, params)

    ctx = ChatContext(
        db=db, user=user, session=s, doc_name=doc_name, message=body.message,
        history=history, slot_state=state.slots, existing_stems=body.existing_stems,
        api_key=api_key, hyde_text=hyde_text, images=body.images,
        progress_cb=progress, cancel_check=lambda: _is_canceled(session_id, run_id),
        on_generate=begin_generation,
    )
    failure_code = None
    try:
        result = base_result(**get_skill(state.mode).run(ctx))
    except chat_flow.NeedConfirmError as exc:
        failure_code = RunErrorCode.NEED_CONFIRM
        result = base_result(reply=f"材料中原题不足（{exc.available}/{exc.requested}），请调整数量或来源模式")
    except LLMError as exc:
        failure_code = error_code(exc)
        result = base_result(reply=friendly_error(exc))
    if result.get("generation_error") is not None:
        failure_code = RunErrorCode(result["generation_error"])
    if switch_prefix:
        result["reply"] = switch_prefix + (result["reply"] or "")
    questions: list[Question] = []
    params = None
    if result["questions"]:
        questions = [Question.model_validate(q) for q in result["questions"]]
        params = generation_params or generation.build_params_from_slots(
            result["slot_state"], bank_id, document_id,
        )
        requested = sum(t.count for t in params.types)

        def review_fn(candidates, review_params, stems):
            check_canceled()
            return question_review.review_questions(
                db, user_id, candidates, review_params, doc_name, api_key, None,
                progress=lambda percent, stage: progress(last_progress, stage),
                cancel_check=check_canceled,
            )

        directive = ""
        if state.mode == "creative":
            directive = CREATIVE_SYSTEM_EXTRA
            if result["slot_state"].get("image_note"):
                directive += f"\n参考图片的题型说明：{result['slot_state']['image_note']}"

        def gen_fn(refill_params, stems, report):
            return question_gen.generate_questions(
                refill_params, doc_name, scope=refill_params.scope,
                mixed_difficulty=bool(result["slot_state"].get("mixed_difficulty")),
                existing_stems=stems, api_key=api_key, hyde_text=None,
                directive=directive, progress_cb=report, cancel_check=check_canceled,
            )

        try:
            questions, stats, _ = chat_flow.review_with_refill(
                questions, params, requested, body.existing_stems, review_fn, gen_fn,
                progress_cb=progress, cancel_check=lambda: _is_canceled(session_id, run_id),
            )
        except (chat_flow.NeedConfirmError, LLMError, ValueError) as exc:
            check_canceled()
            failure_code = error_code(exc)
            questions = []
            result["questions"] = []
            result["generation_error"] = failure_code
            if isinstance(exc, chat_flow.NeedConfirmError):
                result["slot_state"].pop("source_mode", None)
                result["done"] = False
                result["reply"] = switch_prefix + chat_flow.CONFIRM_REPLY.format(
                    type_label=exc.type_label, available=exc.available, requested=exc.requested,
                )
            else:
                result["reply"] = switch_prefix + friendly_error(exc)
        else:
            result["questions"] = [q.model_dump() for q in questions]
            result["reply"] = switch_prefix + build_result_reply(
                len(questions), requested, stats, scope=params.scope or None,
                type_label=(TYPE_LABELS[params.types[0].type] if len(params.types) == 1
                            else f"{len(params.types)} 类题型组合"),
            )
            if questions:
                result["slot_state"]["types"] = []
    response = _commit_turn(db, session_id, user_id, bank_id, document_id, run_id, body,
                            state, result, params=params, hyde_text=hyde_text, questions=questions,
                            run=run, failure_code=failure_code)
    return response


def _commit_turn(
    db: Session, session_id: str, user_id: str, bank_id: str, document_id: str,
    run_id: str, body: ChatMessageBody, state: _TurnState, result: dict, *,
    params: GenerateParams | None = None, hyde_text: str | None = None,
    questions: list[Question] | None = None, run: GenerationRun | None = None,
    failure_code: RunErrorCode | None = None,
) -> ChatMessageResponse:
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
            run=run if run is not None and run.run_id is not None else None,
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
    response = ChatMessageResponse.model_validate({
        "reply": result["reply"], "slot_state": result["slot_state"],
        "questions": result["questions"], "done": result["done"], "batch_id": batch_id,
        "kind": result.get("kind", "reply"), "mode": state.mode,
        "mode_changed": result.get("mode_changed", False),
        "suggested_template": result.get("suggested_template"), "confirm": result.get("confirm"),
    })
    if body.request_id is not None:
        request = db.get(ChatRequest, (session_id, str(body.request_id)))
        assert request is not None and request.run_id == run_id and request.status == "running"
        request.status = "done"
        request.batch_id = batch_id
        request.result_json = response.model_copy(update={"questions": []}).model_dump_json()
        if batch_id is not None:
            response.questions = list(_saved_questions(db, s, batch_id))
    if batch_id is None and run is not None and run.run_id is not None:
        _transition_chat_ledger(
            db, session_id, user_id, run_id, RunStatus.FAILED,
            code=failure_code or RunErrorCode.NO_PERSISTABLE_QUESTIONS,
        )
    # 将确定的写入错误与 commit 结果不明区分；所有写入仍在同一事务中。
    db.flush()
    try:
        db.commit()
    except BaseException:
        if run is not None and run.run_id is not None:
            rollback_business(db)
            with SessionLocal() as reader:
                row = reader.get(OpsRun, run_id)
                failure_committed = (
                    batch_id is None and row is not None and row.owner_user_id == user_id
                    and row.session_id == session_id and row.status == RunStatus.FAILED
                )
            if failure_committed:
                run.committed()
            else:
                run.unknown()
        raise
    if run is not None and run.run_id is not None:
        run.committed()
    return response


@router.post("/sessions/{session_id}/confirm")
def confirm_operation(
    session_id: str,
    body: ChatConfirmBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """数据管理高危操作确认：接受执行，拒绝取消。"""
    user_id, auth_version = user.id, user.auth_version
    _get_session(session_id, user, db)
    with conversation_turn(session_id):
        db.rollback()
        try:
            auth.assert_version(db, user_id, auth_version)
            rag_settings.assert_mutations_allowed(db)
            db.execute(update(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == user_id,
            ).values(last_message_at=ChatSession.last_message_at))
            s = _get_session(session_id, user, db)
            resolve_bank_access(db, user, s.bank_id)
            if s.run_status == "running":
                raise AppError("CHAT_BUSY", "本对话已有进行中的请求，请稍后再确认", 409)
            reply = execute_confirmed(
                db, user, body.confirm_id, body.accepted, session_id=s.id, commit=False,
            )
            db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="user",
                               content="接受操作" if body.accepted else "拒绝操作"))
            db.add(ChatMessage(id=new_id("msg"), session_id=s.id, role="assistant", content=reply))
            s.last_message_at = utcnow()
            db.commit()
        except BaseException:
            db.rollback()
            raise
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


@router.get("/sessions/{session_id}/requests/{request_id}")
def read_chat_request(
    session_id: str,
    request_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatRequestResponse:
    """读取属于本会话的指定轮次及其已提交回复。"""
    s = _get_session(session_id, user, db)
    request = db.get(ChatRequest, (session_id, str(request_id)))
    if request is None:
        raise AppError("CHAT_REQUEST_NOT_FOUND", "对话请求不存在", 404)
    return _request_response(db, s, user, request)


def _cancel_active_run(
    db: Session, session_id: str, user_id: str, run_id: str | None,
) -> None:
    changed = db.execute(update(ChatSession).where(
        ChatSession.id == session_id, ChatSession.user_id == user_id,
        ChatSession.run_status == "running", ChatSession.run_id == run_id,
    ).values(canceled_run_id=run_id, run_status="canceled",
             run_progress=0, run_stage="已收到暂停请求").returning(ChatSession.id))
    if changed.scalar_one_or_none() is not None and run_id is not None:
        db.execute(update(ChatRequest).where(
            ChatRequest.session_id == session_id, ChatRequest.run_id == run_id,
            ChatRequest.status == "running",
        ).values(status="canceled"))


@router.post("/sessions/{session_id}/cancel", status_code=202)
def cancel_generation(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request_id: UUID | None = None,
) -> ChatRequestResponse | dict[str, bool]:
    """原子绑定当前运行的取消事实；与开始和最终提交使用同一 SQL 行锁。"""
    s = _get_session(session_id, user, db)
    target_run_id = s.run_id
    user_id, auth_version = user.id, user.auth_version
    db.rollback()
    if request_id is None:
        _cancel_active_run(db, session_id, user_id, target_run_id)
        db.commit()
        return {"canceled": True}
    auth.assert_version(db, user_id, auth_version)
    db.execute(update(ChatSession).where(
        ChatSession.id == session_id, ChatSession.user_id == user_id,
    ).values(run_status=ChatSession.run_status))
    s = _get_session(session_id, user, db)
    request = db.get(ChatRequest, (session_id, str(request_id)), populate_existing=True)
    if request is None:
        request = ChatRequest(
            session_id=session_id, request_id=str(request_id), status="canceled",
            execution_finished_at=utcnow(),
        )
        db.add(request)
    elif request.status == "running":
        _cancel_active_run(db, session_id, user_id, request.run_id)
    db.commit()
    return _request_response(db, s, user, request)


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
    observed_at = utcnow()
    db.execute(update(OpsRun).where(
        OpsRun.entrypoint == RunEntrypoint.CONVERSATION,
        OpsRun.session_id == session_id, OpsRun.owner_user_id == user_id,
        OpsRun.status.in_((RunStatus.ACCEPTED, RunStatus.RUNNING)),
    ).values(
        status=RunStatus.UNKNOWN.value, error_code=RunErrorCode.OUTCOME_UNKNOWN.value,
        last_observed_at=case(
            (OpsRun.last_observed_at > observed_at, OpsRun.last_observed_at),
            else_=observed_at,
        ),
    ).execution_options(synchronize_session=False))
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(s)
    db.commit()
    try:
        cache.get_redis().delete(_slot_key(session_id), _progress_key(session_id))
    except RedisError:
        pass
    return None

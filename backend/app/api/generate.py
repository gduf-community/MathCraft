"""出题接口：异步任务（start + progress 轮询）、同步出题、最近批次（v2 5.5）。"""

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import BankAccess, get_current_user, resolve_bank_access
from app.errors import AppError
from app.models import Document, GenerationBatch, Question, User
from app.models.base import new_id
from app.schemas.api import GenerateStartBody
from app.schemas.auth import ErrorResponse
from app.services import cache, generation
from app.services.phoenix_tracing import trace_run
from app.services.model_settings import require_deepseek_key

router = APIRouter(prefix="/api/generate", tags=["generate"])


def _resolve(access_body: GenerateStartBody, user: User, db: Session) -> BankAccess:
    bank_id = access_body.bank_id or access_body.kb_id
    if not bank_id:
        raise AppError("BANK_NOT_FOUND", "缺少题库 id", status_code=400)
    return resolve_bank_access(db, user, bank_id)


def _validate_ready(access: BankAccess, body: GenerateStartBody, db: Session) -> Document:
    document_id = body.document_id or body.doc_id
    if not document_id:
        raise AppError("DOCUMENT_NOT_FOUND", "缺少文档 id", status_code=400)
    doc = db.get(Document, document_id)
    if doc is None or doc.bank_id != access.bank.id:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在或已被删除", status_code=404)
    if doc.status != "ready":
        raise AppError(
            "DOCUMENT_NOT_READY",
            f"文档尚未完成入库（当前状态 {doc.status}），请稍后再试",
            status_code=400,
        )
    return doc


@router.post("/start", status_code=202)
def start_generation(
    body: GenerateStartBody,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建异步出题任务。同一用户同时只允许一个进行中任务（409 GENERATION_BUSY）。"""
    access = _resolve(body, user, db)
    _validate_ready(access, body, db)
    api_key = require_deepseek_key(db, user.id)
    if not generation.acquire_lock(user.id):
        raise AppError("GENERATION_BUSY", "你已有进行中的出题任务，请等待完成后再试", status_code=409)

    task_id = new_id("task")
    r = cache.get_redis()
    key = cache.PREFIX_GEN_TASK.format(task_id=task_id)
    r.hset(key, mapping={
        "status": "running", "progress": 0, "stage": "任务已创建",
        "user_id": user.id, "bank_id": access.bank.id,
        "document_id": body.document_id or body.doc_id,
    })
    r.expire(key, 1800)
    background.add_task(generation.run_generation_task, task_id, user.id, api_key, body)
    return {"task_id": task_id}


@router.get("/progress/{task_id}")
def get_progress(task_id: str, user: User = Depends(get_current_user)):
    """查询任务进度；任务完成时携带题目与批次 id。"""
    data = generation.read_task(task_id, user_id=user.id)
    if data is None:
        raise AppError("TASK_NOT_FOUND", "任务不存在或已过期", status_code=404)
    return data


@router.post("", responses={
    503: {"model": ErrorResponse, "description": "向量存储或嵌入服务暂不可用"},
})
@trace_run("parameterized")
def generate_sync(
    body: GenerateStartBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """同步出题（脚本与旧前端回退用）。原题数量不足时返回 422 need_confirm。"""
    from app.services.rag import hyde as hyde_mod
    from app.services.rag import question_gen

    access = _resolve(body, user, db)
    doc = _validate_ready(access, body, db)
    api_key = require_deepseek_key(db, user.id)
    params = generation.build_params(body)
    hyde_text = hyde_mod.get_hyde(
        cache.get_redis(), params.kb_id, params.doc_id, body.scope, body.difficulty, api_key
    )
    try:
        questions = question_gen.generate_questions(
            params,
            doc.name,
            scope=body.scope or None,
            existing_stems=body.existing_stems,
            api_key=api_key,
            hyde_text=hyde_text,
        )
    except question_gen.NeedConfirmError as exc:
        raise AppError(
            "NEED_CONFIRM",
            f"材料中「{exc.type_label}」的原题只有 {exc.available} 道，不足 {exc.requested} 道",
            status_code=422,
            kind="need_confirm",
            available=exc.available,
            requested=exc.requested,
        ) from exc
    from app.services import question_review

    questions, _stats = question_review.review_questions(
        db, user.id, questions, params, doc.name, api_key, hyde_text
    )
    generation.persist_batch(
        db, user.id, access.bank.id, doc.id, "parametric", params, hyde_text, questions
    )
    return [q.model_dump() for q in questions]


@router.get("/batches/latest")
def latest_batch(
    bank_id: str = "",
    document_id: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前用户最近一次生成批次及题目（刷新后恢复）。"""
    q = db.query(GenerationBatch).filter(
        GenerationBatch.user_id == user.id, GenerationBatch.status == "done"
    )
    if bank_id:
        q = q.filter(GenerationBatch.bank_id == bank_id)
    if document_id:
        q = q.filter(GenerationBatch.document_id == document_id)
    batch = q.order_by(GenerationBatch.created_at.desc()).first()
    if batch is None:
        return {"batch_id": None, "questions": []}
    rows = db.query(Question).filter(Question.batch_id == batch.id).order_by(Question.created_at).all()
    doc_names = {
        d.id: d.name
        for d in db.query(Document).filter(Document.id.in_({r.document_id for r in rows}))
    } if rows else {}
    return {
        "batch_id": batch.id,
        "questions": [
            generation.question_to_api(r, doc_name=doc_names.get(r.document_id, "")) for r in rows
        ],
    }

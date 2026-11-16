"""出题接口：异步任务（start + progress 轮询）、同步出题、最近批次（v2 5.5）。"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import BankAccess, get_current_user, resolve_bank_access
from app.errors import AppError
from app.models import Document, GenerationBatch, Question, User
from app.models.ops_run import RunEntrypoint, RunErrorCode
from app.schemas.api import (
    GenerateCancellationResponse,
    GenerateProgressResponse,
    GenerateStartBody,
    GenerateTaskResponse,
)
from app.schemas.auth import ErrorResponse
from app.services import auth, generation, rag_settings
from app.services.generation_lifecycle import GenerationRun, rollback_business
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


@router.post("/start", status_code=202, response_model=GenerateTaskResponse)
def start_generation(
    body: GenerateStartBody,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建异步出题任务。同一用户同时只允许一个进行中任务（409 GENERATION_BUSY）。"""
    user_id, auth_version = user.id, user.auth_version
    if body.request_id is not None and generation.find_request(db, user_id, str(body.request_id)):
        task, _ = generation.accept_task_once(db, user_id, body, auth_version=auth_version)
        return {"task_id": task.id}
    access = _resolve(body, user, db)
    _validate_ready(access, body, db)
    api_key = require_deepseek_key(db, user.id)
    task, created = generation.accept_task_once(db, user_id, body, auth_version=auth_version)
    if not created:
        return {"task_id": task.id}
    try:
        background.add_task(
            generation.run_generation_task, task.id, user_id, api_key, body, run_id=task.run_id,
            auth_version=auth_version,
        )
    except Exception:
        generation.fail_submission(task)
        raise
    return {"task_id": task.id}


@router.get("/requests/{request_id}", response_model=GenerateTaskResponse)
def find_generation_request(
    request_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """在当前账号内找回启动响应丢失的原任务。"""
    task = generation.find_request(db, user.id, str(request_id))
    if task is None:
        raise AppError("TASK_NOT_FOUND", "任务不存在", 404)
    return {"task_id": task.id}


@router.post("/cancel/{task_id}", response_model=GenerateCancellationResponse, responses={
    202: {"model": GenerateCancellationResponse, "description": "取消已受理，等待后台执行退出"},
})
def cancel_generation_task(
    task_id: str, response: Response, user: User = Depends(get_current_user),
):
    """幂等取消指定任务；正在执行时保留忙碌门禁直到全部工作退出。"""
    state = generation.cancel_task(task_id, user.id, user.auth_version)
    if state["status"] == "canceling":
        response.status_code = 202
    return state


@router.get("/progress/{task_id}", response_model=GenerateProgressResponse)
def get_progress(task_id: str, user: User = Depends(get_current_user)):
    """查询任务进度；任务完成时携带题目与批次 id。"""
    data = generation.read_task(task_id, user_id=user.id)
    if data is None:
        raise AppError(
            "TASK_NOT_FOUND",
            "任务不存在、已失效或属于升级前任务；请检查最近生成批次，未完成的任务请重新生成",
            status_code=404,
        )
    return data


@router.post("", responses={
    503: {"model": ErrorResponse, "description": "向量存储或嵌入服务暂不可用"},
})
@trace_run("parameterized", force_new=True)
def generate_sync(
    body: GenerateStartBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """同步出题（脚本与旧前端回退用）。原题数量不足时返回 422 need_confirm。"""
    from app.services.rag import question_gen

    auth_version = user.auth_version
    access = _resolve(body, user, db)
    doc = _validate_ready(access, body, db)
    api_key = require_deepseek_key(db, user.id)
    params = generation.build_params(body)
    user_id, bank_id, document_id, doc_name = user.id, access.bank.id, doc.id, doc.name
    db.rollback()
    run = GenerationRun(RunEntrypoint.PARAMETERIZED, user_id, bank_id, document_id)
    with run.observe(db):
        run.begin(params)
        hyde_text = generation.get_hyde(params, body, api_key)
        try:
            questions = question_gen.generate_questions(
                params,
                doc_name,
                scope=body.scope or None,
                existing_stems=body.existing_stems,
                api_key=api_key,
                hyde_text=hyde_text,
            )
        except question_gen.NeedConfirmError as exc:
            run.fail(RunErrorCode.NEED_CONFIRM)
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
            db, user_id, questions, params, doc_name, api_key, hyde_text
        )
        db.rollback()
        auth.assert_version(db, user_id, auth_version)
        rag_settings.assert_mutations_allowed(db)
        generation.validate_resources(db, user_id, bank_id, document_id)
        generation.persist_batch(
            db, user_id, bank_id, document_id, "parametric", params, hyde_text, questions,
            commit=False, run=run,
        )
        try:
            db.commit()
        except BaseException:
            rollback_business(db)
            run.unknown()
            raise
        run.committed()
        return [q.model_dump() for q in questions]


@router.get("/batches/latest")
def latest_batch(
    bank_id: str = "",
    document_id: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """恢复最近批次前重检当前资源权限；失效资料不再恢复题目。"""
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
    try:
        document = generation.validate_resources(db, user.id, batch.bank_id, batch.document_id)
    except AppError:
        return {"batch_id": None, "questions": []}
    rows = db.query(Question).filter(Question.batch_id == batch.id).order_by(Question.created_at).all()
    return {
        "batch_id": batch.id,
        "questions": [
            generation.question_to_api(r, doc_name=document.name) for r in rows
        ],
    }

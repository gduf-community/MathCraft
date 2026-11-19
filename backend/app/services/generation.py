"""持久出题任务：无写锁调用模型，SQL 原子发布批次与终态，Redis 仅作缓存。"""
from datetime import datetime
from collections.abc import Callable
import json
import logging

from redis.exceptions import RedisError
from sqlalchemy import case, inspect, select
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.deps import resolve_bank_access
from app.errors import AppError
from app.models import Document, GenerationBatch, OpsRun, Question, User
from app.models.chat import ChatRequest, ChatSession
from app.models.base import new_id, utcnow
from app.models.generation_task import GenerationTask
from app.models.ops_run import RunEntrypoint, RunErrorCode, RunStatus
from app.schemas.api import GenerateStartBody
from app.schemas.question import Difficulty, GenerateParams, QuestionType, TypeCount
from app.schemas.question import Question as GeneratedQuestion
from app.services import auth, cache, question_review, rag_settings
from app.services.generation_lifecycle import GenerationRun, error_code, rollback_business
from app.services.generation_cancellation import GenerationCanceled, cancellation_kwargs
from app.services.ops_runs import RunLedger
from app.services.phoenix_tracing import trace_run
from app.services.rag import hyde, llm, question_gen
from app.services.rag.question_gen import NeedConfirmError

logger = logging.getLogger("app.generation")


def _task_key(task_id: str) -> str:
    return cache.PREFIX_GEN_TASK.format(task_id=task_id)


ACTIVE_TASK_STATUSES = ("queued", "running", "canceling")
_LEASE_SECONDS = 120
_RENEW_LEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_LEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def acquire_lock(user_id: str, token: str) -> bool:
    """取得辅助租约；Redis 不可用时由持久 SQL 门禁保证互斥。"""
    try:
        return bool(cache.get_redis().set(
            cache.PREFIX_GEN_LOCK.format(user_id=user_id), token, nx=True, ex=_LEASE_SECONDS,
        ))
    except RedisError:
        return False


def renew_lock(user_id: str, token: str) -> bool:
    """只有持有同一 task/run token 的执行者可以续租。"""
    try:
        return bool(cache.get_redis().eval(
            _RENEW_LEASE, 1, cache.PREFIX_GEN_LOCK.format(user_id=user_id),
            token, _LEASE_SECONDS,
        ))
    except RedisError:
        return False


def release_lock(user_id: str, token: str) -> bool:
    """比较并释放，旧任务不能删除后继任务租约。"""
    try:
        return bool(cache.get_redis().eval(
            _RELEASE_LEASE, 1, cache.PREFIX_GEN_LOCK.format(user_id=user_id), token,
        ))
    except RedisError:
        return False


def validate_resources(db: Session, user_id: str, bank_id: str, document_id: str) -> Document:
    """从 SQL 重新验证账号、题库成员与 ready 文档。最终写入须先取得资料门禁。"""
    user = db.get(User, user_id, populate_existing=True)
    if user is None or user.status != "active":
        raise AppError("FORBIDDEN", "账号不可用", 403)
    db.expire_all()
    resolve_bank_access(db, user, bank_id)
    doc = db.get(Document, document_id, populate_existing=True)
    if doc is None or doc.bank_id != bank_id:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在或已被删除", 404)
    if doc.status != "ready":
        raise AppError("DOCUMENT_NOT_READY", "文档不可用，请重新上传", 400)
    return doc


def accept_task(
    db: Session, user_id: str, body: GenerateStartBody, mode: str = "parametric",
    *, auth_version: int | None = None,
) -> GenerationTask:
    """受理或找回同一请求，兼容直接调用任务服务的既有入口。"""
    return accept_task_once(db, user_id, body, mode, auth_version=auth_version)[0]


def accept_task_once(
    db: Session, user_id: str, body: GenerateStartBody, mode: str = "parametric",
    *, auth_version: int | None = None,
) -> tuple[GenerationTask, bool]:
    """串行化同一用户受理，并在返回 task_id 前提交 SQL。"""
    bank_id = body.bank_id or body.kb_id or ""
    document_id = body.document_id or body.doc_id or ""
    if auth_version is None:
        user = db.get(User, user_id)
        auth_version = user.auth_version if user else -1
    db.rollback()
    # 复用账号门禁，同时核对请求原认证版本，不能采用 rollback 后刷新的版本。
    auth.assert_version(db, user_id, auth_version)
    if body.request_id is not None:
        existing = db.query(GenerationTask).filter(
            GenerationTask.user_id == user_id, GenerationTask.request_id == str(body.request_id),
        ).one_or_none()
        if existing is not None:
            previous = GenerateStartBody.model_validate_json(existing.params_json)
            if previous != body or existing.mode != mode:
                db.rollback()
                raise AppError("GENERATION_REQUEST_CONFLICT", "请求标识已用于其他出题参数", 409)
            db.commit()
            return existing, False
    validate_resources(db, user_id, bank_id, document_id)
    if db.query(GenerationTask.id).filter(
        GenerationTask.user_id == user_id,
        (GenerationTask.status.in_(ACTIVE_TASK_STATUSES))
        | GenerationTask.execution_finished_at.is_(None),
    ).first():
        db.rollback()
        raise AppError("GENERATION_BUSY", "你已有进行中的出题任务，请等待完成后再试", 409)
    task = GenerationTask(
        id=new_id("task"), run_id=new_id("run"), user_id=user_id,
        bank_id=bank_id, document_id=document_id, mode=mode, params_json=body.model_dump_json(),
        request_id=str(body.request_id) if body.request_id is not None else None,
    )
    db.add(task)
    run = GenerationRun(
        RunEntrypoint.PARAMETERIZED, user_id, bank_id, document_id,
        task_id=task.id, run_id=task.run_id,
    )
    run.accept(build_params(body), db=db)
    db.commit()
    run.register_accepted()
    # 缓存失败或残留租约不能推翻已提交的任务受理。
    acquire_lock(user_id, f"{task.id}:{task.run_id}")
    _cache_task(task)
    return task, True


def _cache_task(task: GenerationTask) -> None:
    """SQL 提交后的尽力缓存，不参与完成判定或权限判定。"""
    try:
        r = cache.get_redis()
        r.hset(_task_key(task.id), mapping={
            "user_id": task.user_id, "run_id": task.run_id, "status": task.status,
            "progress": task.progress, "stage": task.stage,
        })
        r.expire(_task_key(task.id), settings.generate_task_ttl_seconds)
    except RedisError:
        logger.debug("出题进度缓存不可用；进度继续从 SQL 读取")


def find_request(db: Session, user_id: str, request_id: str) -> GenerationTask | None:
    """仅在调用者账号范围内找回已受理请求，不读取模型配置或资料。"""
    return db.query(GenerationTask).filter(
        GenerationTask.user_id == user_id, GenerationTask.request_id == request_id,
    ).one_or_none()


def cancel_task(task_id: str, user_id: str, auth_version: int) -> dict:
    """取消与认领、发布竞争 SQL 门禁，已运行任务等待执行器确认退出。"""
    with SessionLocal() as db:
        auth.assert_version(db, user_id, auth_version)
        task = db.query(GenerationTask).filter(
            GenerationTask.id == task_id, GenerationTask.user_id == user_id,
        ).one_or_none()
        if task is None:
            raise AppError("TASK_NOT_FOUND", "任务不存在", 404)
        if task.status == "queued":
            task.status = "canceled"
            task.stage = "已取消"
            task.execution_finished_at = utcnow()
            RunLedger().cancel_in_transaction(db, task.run_id)
        elif task.status == "running":
            task.status = "canceling"
            task.stage = "正在取消，等待后台退出"
        db.commit()
        if task.status == "canceled":
            release_lock(user_id, f"{task.id}:{task.run_id}")
            GenerationRun(
                RunEntrypoint.PARAMETERIZED, user_id, task.bank_id, task.document_id,
                task_id=task.id, run_id=task.run_id,
            ).committed()
        _cache_task(task)
    result = read_task(task_id, user_id, validate_material=False)
    if result is None:
        raise AppError("TASK_NOT_FOUND", "任务不存在", 404)
    with SessionLocal() as db:
        result["question_ids"] = list(db.scalars(
            select(Question.id).join(GenerationBatch, GenerationBatch.id == Question.batch_id)
            .join(GenerationTask, GenerationTask.batch_id == GenerationBatch.id)
            .where(GenerationTask.id == task_id, GenerationTask.user_id == user_id,
                   GenerationBatch.user_id == user_id, Question.created_by == user_id)
        ))
    return result


def _check_execution(task_id: str, run_id: str, user_id: str) -> None:
    """每次读取新 SQL 快照，取消或过期执行不能继续模型工作。"""
    with SessionLocal() as db:
        valid = db.query(GenerationTask.id).filter(
            GenerationTask.id == task_id, GenerationTask.run_id == run_id,
            GenerationTask.user_id == user_id, GenerationTask.status == "running",
        ).first()
        if valid is None:
            raise GenerationCanceled()


def _finish_execution(task_id: str, run_id: str, user_id: str, run: GenerationRun) -> None:
    """所属线程工作均结束后原子记录退出；只有当前代次能收束取消。"""
    with SessionLocal() as db:
        changed = db.query(GenerationTask).filter(
            GenerationTask.id == task_id, GenerationTask.run_id == run_id,
            GenerationTask.user_id == user_id,
        ).update({"execution_finished_at": utcnow()}, synchronize_session=False)
        if not changed:
            db.rollback()
            _observe_run(run, code=RunErrorCode.EXECUTION_INTERRUPTED, unknown=True)
            return
        task = db.get(GenerationTask, task_id, populate_existing=True)
        if task is None:
            return
        canceled = task.status == "canceling"
        interrupted = task.status in ("queued", "running")
        if canceled:
            task.status = "canceled"
            task.stage = "已取消"
            task.result_json = task.review_json = task.error_json = None
            RunLedger().cancel_in_transaction(db, run_id)
        elif interrupted:
            task.status = "interrupted"
            task.stage = "执行已中断，请重新生成"
            task.error_json = json.dumps({"message": "执行已中断，请重新生成"}, ensure_ascii=False)
        db.commit()
        if canceled:
            run.committed()
        elif interrupted:
            _observe_run(run, code=RunErrorCode.EXECUTION_INTERRUPTED, unknown=True)


def _write_progress(
    task_id: str, percent: int, stage: str, *, run_id: str,
) -> None:
    """短事务更新运行中的持久进度；过期执行者不能覆盖终态。"""
    with SessionLocal() as db:
        query = db.query(GenerationTask).filter(
            GenerationTask.id == task_id, GenerationTask.status == "running",
            GenerationTask.run_id == run_id,
        )
        if not query.update({"progress": min(99, max(0, percent)), "stage": stage},
                            synchronize_session=False):
            db.rollback()
            return
        db.commit()
        task = db.get(GenerationTask, task_id, populate_existing=True)
        if task is not None:
            _cache_task(task)
            renew_lock(task.user_id, f"{task_id}:{run_id}")


def get_hyde(
    params: GenerateParams, body: GenerateStartBody, api_key: str,
    cancel_check: Callable[[], None] | None = None,
) -> str | None:
    """可选 HyDE 缓存故障不阻断题目生成。"""
    return get_cached_hyde(
        params.kb_id, params.doc_id, body.scope, body.difficulty, api_key,
        **cancellation_kwargs(cancel_check),
    )


def get_cached_hyde(
    bank_id: str, document_id: str, scope: str, difficulty: str, api_key: str,
    cancel_check: Callable[[], None] | None = None,
) -> str | None:
    """复用 HyDE 生成与键格式；缓存读写失败不丢弃本轮生成结果。"""
    scope = scope.strip()
    if not scope or not api_key:
        return None
    key = cache.PREFIX_HYDE.format(digest=hyde._digest(bank_id, document_id, scope, difficulty))
    try:
        cached = cache.get_redis().get(key)
        if isinstance(cached, str) and cached:
            return cached
    except RedisError:
        logger.warning("HyDE 缓存读取失败，继续本轮生成")
    generated = hyde.generate_hyde(scope, api_key, **cancellation_kwargs(cancel_check))
    if generated:
        try:
            cache.get_redis().set(key, generated, ex=hyde._HYDE_TTL)
        except RedisError:
            logger.warning("HyDE 缓存写入失败，保留本轮生成结果")
    return generated


def persist_batch(
    db: Session,
    user_id: str,
    bank_id: str,
    document_id: str,
    mode: str,
    params: GenerateParams,
    hyde_text: str | None,
    questions: list[GeneratedQuestion],
    *,
    commit: bool = True,
    run: GenerationRun | None = None,
) -> GenerationBatch:
    """写入批次、题目及可选台账；commit=False 时由调用者一起提交。"""
    batch = GenerationBatch(
        id=new_id("batch"),
        user_id=user_id,
        bank_id=bank_id,
        document_id=document_id,
        mode=mode,
        params_json=params.model_dump_json(),
        hyde_text=hyde_text,
        question_count=len(questions),
        status="done",
    )
    db.add(batch)
    db.flush()
    for q in questions:
        if not q.id:
            q.id = new_id("q")
        db.add(
            Question(
                id=q.id,
                batch_id=batch.id,
                bank_id=bank_id,
                document_id=document_id,
                type=q.type.value,
                score=q.score,
                difficulty=q.difficulty.value,
                difficulty_score=float(q.difficultyScore or 0),
                blueprint_json=json.dumps(q.blueprint, ensure_ascii=False) if q.blueprint else None,
                review_json=json.dumps(q.difficultyReview, ensure_ascii=False) if q.difficultyReview else None,
                stem=q.stem,
                options_json=json.dumps([o.model_dump() for o in q.options], ensure_ascii=False) if q.options else None,
                answer=q.answer,
                analysis=q.analysis,
                knowledge_point=q.knowledgePoint or None,
                source_mode=params.source_mode,
                created_by=user_id,
            )
        )
    db.flush()
    if run is not None:
        run.complete_in_transaction(db, batch.id)
    if commit:
        try:
            db.commit()
        except BaseException:
            if run is not None:
                rollback_business(db)
                run.unknown()
            raise
        if run is not None:
            run.committed()
    return batch


def question_to_api(
    row: Question,
    starred: bool = False,
    favorite_group_id: str | None = None,
    doc_name: str = "",
) -> dict:
    """DB 行 → API 载荷（snake_case，v2 5.7）。"""
    return {
        "id": row.id,
        "type": row.type,
        "score": row.score,
        "difficulty": row.difficulty,
        "difficulty_score": round(float(row.difficulty_score or 0), 2),
        "difficulty_review": json.loads(row.review_json) if row.review_json else None,
        "stem": row.stem,
        "options": json.loads(row.options_json) if row.options_json else [],
        "answer": row.answer,
        "analysis": row.analysis,
        "knowledge_point": row.knowledge_point or "",
        "starred": starred,
        "favorite_group_id": favorite_group_id,
        "doc_name": doc_name,
        "bank_id": row.bank_id,
        "document_id": row.document_id,
        "batch_id": row.batch_id,
        "created_at": row.created_at,
    }


def build_params(body: GenerateStartBody) -> GenerateParams:
    """将兼容 HTTP 请求统一转换为内部出题参数。"""
    bank_id = body.bank_id or body.kb_id or ""
    document_id = body.document_id or body.doc_id or ""
    return GenerateParams(
        kb_id=bank_id,
        doc_id=document_id,
        types=[
            TypeCount(
                type=QuestionType(t.type), count=t.count,
                difficulty=Difficulty(t.difficulty) if t.difficulty else None,
            )
            for t in body.types
        ],
        difficulty=Difficulty(body.difficulty),
        source_mode=body.source_mode,
        scope=body.scope,
        existing_stems=body.existing_stems,
    )


def build_params_from_slots(slot_state: dict, bank_id: str, document_id: str) -> GenerateParams:
    """从对话槽位构造出题参数（对话路径持久化批次用）。"""
    from app.services.rag.slots import build_params as _from_slots

    params, _scope = _from_slots(slot_state or {}, bank_id, document_id)
    return params


@trace_run("parameterized", run_id_kwarg="run_id", force_new=True)
def run_generation_task(
    task_id: str, user_id: str, api_key: str, body: GenerateStartBody,
    mode: str = "parametric", *, run_id: str | None = None,
    auth_version: int | None = None,
) -> None:
    """先持久认领，再无写锁调用模型；批次与任务完成在同一 SQL 事务提交。"""
    # 后台分发带有任务 run；认领前读取异常时也必须能把 queued 收束为 failed，
    # 否则受理门禁会永久认为存在进行中任务。
    owns_run = run_id is not None
    claimed = False
    committing = False
    run = GenerationRun(
        RunEntrypoint.PARAMETERIZED, user_id, body.bank_id or body.kb_id or "",
        body.document_id or body.doc_id or "", task_id=task_id, run_id=run_id,
    )
    try:
        with SessionLocal() as db:
            task = db.get(GenerationTask, task_id)
            if (task is None or task.user_id != user_id or task.status != "queued"
                    or (run_id and task.run_id != run_id)):
                owns_run = False
                return
            run_id = task.run_id
            run.run_id = run_id
            owns_run = True
            body = GenerateStartBody.model_validate_json(task.params_json)
            mode = task.mode
            if auth_version is None:
                user = db.get(User, user_id)
                auth_version = user.auth_version if user else -1
            auth.assert_version(db, user_id, auth_version)
            changed = db.query(GenerationTask).filter(
                GenerationTask.id == task_id, GenerationTask.user_id == user_id,
                GenerationTask.run_id == run_id, GenerationTask.status == "queued",
            ).update({"status": "running", "stage": "准备生成"}, synchronize_session=False)
            if not changed:
                owns_run = False
                return
            db.commit()
            claimed = True
        params = build_params(body)
        def check_canceled() -> None:
            _check_execution(task_id, run_id, user_id)

        check_canceled()
        run.begin(params)
        _write_progress(task_id, 2, "准备生成", run_id=run_id)
        with SessionLocal() as db:
            doc_name = validate_resources(db, user_id, params.kb_id, params.doc_id).name
        check_canceled()
        hyde_text = get_hyde(
            params, body, api_key, **cancellation_kwargs(check_canceled),
        )
        check_canceled()
        if body.scope and hyde_text:
            _write_progress(task_id, 5, "已生成假设文档（HyDE），正在混合检索", run_id=run_id)
        def progress(percent: int, stage: str) -> None:
            check_canceled()
            _write_progress(task_id, percent, stage, run_id=run_id)
        questions = question_gen.generate_questions(
            params, doc_name, scope=body.scope or None, existing_stems=body.existing_stems,
            progress_cb=progress, api_key=api_key, hyde_text=hyde_text,
            cancel_check=check_canceled,
        )
        check_canceled()
        with SessionLocal() as db:
            questions, stats = question_review.review_questions(
                db, user_id, questions, params, doc_name, api_key, hyde_text, progress=progress,
                cancel_check=check_canceled,
            )
            # 审核仅作读操作；结束旧快照后再进入短写事务。
            db.rollback()
            auth.assert_version(db, user_id, auth_version)
            rag_settings.assert_mutations_allowed(db)
            current = db.query(GenerationTask).filter(
                GenerationTask.id == task_id, GenerationTask.user_id == user_id,
                GenerationTask.run_id == run_id, GenerationTask.status == "running",
            ).update({"stage": "正在写入题目"}, synchronize_session=False)
            if not current:
                db.rollback()
                raise GenerationCanceled()
            validate_resources(db, user_id, params.kb_id, params.doc_id)
            task = db.get(GenerationTask, task_id, populate_existing=True)
            if task is None or task.bank_id != params.kb_id or task.document_id != params.doc_id:
                raise AppError("TASK_NOT_FOUND", "任务资源已变更", 409)
            batch = persist_batch(
                db, user_id, params.kb_id, params.doc_id, mode, params, hyde_text, questions,
                commit=False, run=run,
            )
            task.status = "done"
            task.progress = 100
            task.stage = "生成完成"
            task.batch_id = batch.id
            task.result_json = json.dumps([q.model_dump() for q in questions], ensure_ascii=False)
            task.review_json = json.dumps({
                "duplicates": stats.duplicates, "repaired": stats.repaired,
                "regenerated": stats.regenerated, "solved": stats.solved,
            }, ensure_ascii=False)
            task.error_json = None
            committing = True
            db.commit()
            committing = False
            run.committed()
            _cache_task(task)
    except GenerationCanceled:
        pass
    except NeedConfirmError as exc:
        label = exc.type_label if exc.type_label in question_gen.TYPE_LABELS.values() else "材料"
        if owns_run and run_id is not None:
            changed = _fail_task(task_id, run_id, {
                "kind": "need_confirm",
                "message": f"{label}原题仅 {exc.available} 道，不足 {exc.requested} 道",
                "available": exc.available, "requested": exc.requested,
            }, user_id=user_id)
            if changed:
                _observe_run(run, code=RunErrorCode.NEED_CONFIRM)
    except Exception as exc:
        if owns_run and run_id is not None:
            changed = _fail_task(
                task_id, run_id, {"message": llm.friendly_error(exc)}, user_id=user_id,
                statuses=("running",) if claimed else ("queued",),
            )
            if committing:
                _observe_run(run, unknown=True)
            elif changed:
                _observe_run(run, code=error_code(exc))
            if not claimed:
                owns_run = changed
    except BaseException:
        if owns_run and run_id is not None:
            _observe_run(run, code=RunErrorCode.EXECUTION_INTERRUPTED, unknown=True)
        raise
    finally:
        if owns_run and run_id is not None:
            try:
                release_lock(user_id, f"{task_id}:{run_id}")
            finally:
                _finish_execution(task_id, run_id, user_id, run)


def _observe_run(
    run: GenerationRun, *, code: RunErrorCode | None = None,
    unknown: bool = False,
) -> None:
    """记录台账失败或中断，不让观测失败覆盖已处理的任务结果。"""
    try:
        if unknown:
            run.unknown(code or RunErrorCode.OUTCOME_UNKNOWN)
        else:
            run.fail(code or RunErrorCode.EXECUTION_ERROR)
    except (SQLAlchemyError, ValueError):
        logger.error("Generation outcome could not be recorded")


def fail_submission(task: GenerationTask) -> None:
    """后台派发失败时收束任务和台账，并释放当前任务的租约。"""
    run = GenerationRun(
        RunEntrypoint.PARAMETERIZED, task.user_id, task.bank_id, task.document_id,
        task_id=task.id, run_id=task.run_id,
    )
    try:
        changed = _fail_task(
            task.id, task.run_id, {"message": "任务派发失败，请重新发起生成"},
            user_id=task.user_id, statuses=("queued",),
        )
        if changed:
            _observe_run(run, code=RunErrorCode.TASK_SUBMISSION_ERROR)
    finally:
        release_lock(task.user_id, f"{task.id}:{task.run_id}")
        _finish_execution(task.id, task.run_id, task.user_id, run)


def _fail_task(
    task_id: str, run_id: str, error: dict, *, user_id: str,
    statuses: tuple[str, ...] = ("queued", "running"),
) -> bool:
    """仅当前执行者能够写失败状态，不能覆盖已提交结果或恢复后的中断状态。"""
    with SessionLocal() as db:
        changed = db.query(GenerationTask).filter(
            GenerationTask.id == task_id, GenerationTask.run_id == run_id,
            GenerationTask.user_id == user_id,
            GenerationTask.status.in_(statuses),
        ).update({"status": "failed", "stage": "生成失败",
                  "error_json": json.dumps(error, ensure_ascii=False)}, synchronize_session=False)
        db.commit()
        if changed:
            task = db.get(GenerationTask, task_id, populate_existing=True)
            if task is not None:
                _cache_task(task)
        return bool(changed)


def read_task(
    task_id: str, user_id: str | None = None, *, validate_material: bool = True,
) -> dict | None:
    """只依据 SQL 所有者返回完整状态；缺少归属或身份时默认拒绝。"""
    if not user_id:
        return None
    with SessionLocal() as db:
        task = db.query(GenerationTask).filter(
            GenerationTask.id == task_id, GenerationTask.user_id == user_id,
        ).one_or_none()
        if task is None:
            return None
        material_available = True
        if task.status not in ("canceling", "canceled", "interrupted"):
            try:
                validate_resources(db, user_id, task.bank_id, task.document_id)
            except AppError:
                if validate_material:
                    return None
                material_available = False
        batch_id = task.batch_id
        questions = json.loads(task.result_json) if task.result_json else []
        review = json.loads(task.review_json) if task.review_json else None
        error = json.loads(task.error_json) if task.error_json else None
        if not material_available:
            batch_id, questions, review = None, [], None
            error = {"message": "生成资料已不可用"}
        if task.status == "done":
            batch = db.get(GenerationBatch, batch_id) if batch_id else None
            if (batch is None or batch.user_id != user_id or batch.status != "done"
                    or batch.bank_id != task.bank_id or batch.document_id != task.document_id
                    or db.query(Question).filter(Question.batch_id == batch_id).count()
                    != len(questions)):
                batch_id, questions, review = None, [], None
                error = {"message": "生成结果已删除或失效，请检查最近批次或重新生成"}
        return {
            "status": task.status,
            "execution_finished": task.execution_finished_at is not None,
            "progress": task.progress, "stage": task.stage,
            "review": review,
            "done": (task.status not in ACTIVE_TASK_STATUSES
                     and task.execution_finished_at is not None),
            "batch_id": batch_id,
            "questions": questions,
            "error": error,
        }


def _ops_recovery_schema_available(db: Session) -> bool:
    """只接受可执行中断状态恢复的台账结构，数据库读取错误继续向外传播。"""
    table = OpsRun.metadata.tables[OpsRun.__tablename__]
    inspector = inspect(db.connection())
    if not inspector.has_table(table.name, schema=table.schema):
        return False
    try:
        columns = {column["name"]: column for column in inspector.get_columns(
            table.name, schema=table.schema,
        )}
    except NoSuchTableError:
        return False
    for name, expected in (
        ("run_id", str), ("entrypoint", str), ("status", str), ("error_code", str),
        ("last_observed_at", datetime),
    ):
        column = columns.get(name)
        if column is None:
            return False
        try:
            if not issubclass(column["type"].python_type, expected):
                return False
        except (NotImplementedError, TypeError):
            return False
    for name, value in (
        ("status", RunStatus.UNKNOWN.value),
        ("error_code", RunErrorCode.EXECUTION_INTERRUPTED.value),
    ):
        length = getattr(columns[name]["type"], "length", None)
        if length is not None and length < len(value):
            return False
    return True


def recover_interrupted_generation() -> None:
    """单 worker 启动时标记中断，不重新调用模型，由用户显式重试。"""
    with SessionLocal() as db:
        tasks = db.query(GenerationTask).filter(
            (GenerationTask.status.in_(ACTIVE_TASK_STATUSES))
            | GenerationTask.execution_finished_at.is_(None),
        ).all()
        for task in tasks:
            task.execution_finished_at = utcnow()
            if task.status in ACTIVE_TASK_STATUSES:
                task.status = "interrupted"
                task.stage = "服务重启，生成已中断"
                task.error_json = json.dumps({"message": "服务重启，请重新发起生成"}, ensure_ascii=False)
        if _ops_recovery_schema_available(db):
            observed_at = utcnow()
            task_runs = select(GenerationTask.run_id).where(
                GenerationTask.status.in_((*ACTIVE_TASK_STATUSES, "failed", "interrupted")),
            )
            db.query(OpsRun).filter(
                OpsRun.status.in_((RunStatus.ACCEPTED.value, RunStatus.RUNNING.value)),
                # 启动恢复仅适用于没有其他共享数据库执行实例的单 worker 部署。
                (OpsRun.entrypoint == RunEntrypoint.CONVERSATION.value)
                | OpsRun.run_id.in_(task_runs),
            ).update({
                "status": RunStatus.UNKNOWN.value,
                "error_code": RunErrorCode.EXECUTION_INTERRUPTED.value,
                "last_observed_at": case(
                    (OpsRun.last_observed_at > observed_at, OpsRun.last_observed_at),
                    else_=observed_at,
                ),
            }, synchronize_session=False)
        else:
            logger.warning("运维台账结构不可用，已跳过台账中断状态恢复")
        db.query(ChatSession).filter(ChatSession.run_status == "running").update({
            "run_status": "interrupted", "run_stage": "服务重启，请重新发送消息",
        }, synchronize_session=False)
        db.query(ChatRequest).filter(ChatRequest.execution_finished_at.is_(None)).update({
            "status": case(
                (ChatRequest.status == "running", "interrupted"), else_=ChatRequest.status,
            ),
            "execution_finished_at": utcnow(),
        }, synchronize_session=False)
        db.commit()
        for task in tasks:
            release_lock(task.user_id, f"{task.id}:{task.run_id}")
            _cache_task(task)

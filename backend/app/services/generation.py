"""出题任务编排：HyDE → 混合检索 → 分题型生成 → 中间件校验 → 批次/题目落库 → Redis 进度。"""
import json
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import GenerationBatch, Question
from app.models.base import new_id
from app.models.ops_run import RunEntrypoint, RunErrorCode
from app.schemas.api import GenerateStartBody
from app.schemas.question import Difficulty, GenerateParams, QuestionType, TypeCount
from app.schemas.question import Question as GeneratedQuestion
from app.services import cache, question_review
from app.services.generation_lifecycle import GenerationRun, error_code, rollback_business
from app.services.phoenix_tracing import trace_run
from app.services.rag import hyde, llm, question_gen
from app.services.rag.question_gen import NeedConfirmError

logger = logging.getLogger("app.generation")


def _task_key(task_id: str) -> str:
    return cache.PREFIX_GEN_TASK.format(task_id=task_id)


def _write_progress(task_id: str, percent: int, stage: str, **fields) -> None:
    r = cache.get_redis()
    mapping = {"progress": int(percent), "stage": stage}
    mapping.update({
        k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v))
        for k, v in fields.items()
    })
    r.hset(_task_key(task_id), mapping=mapping)
    r.expire(_task_key(task_id), settings.generate_task_ttl_seconds)


def persist_batch(
    db: Session,
    user_id: str,
    bank_id: str,
    document_id: str,
    mode: str,
    params: GenerateParams,
    hyde_text: str | None,
    questions: list[GeneratedQuestion],
    *, run: GenerationRun | None = None,
) -> GenerationBatch:
    """把生成结果写入 generation_batches + questions，返回批次。"""
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
    committing = False
    try:
        db.add(batch)
        db.flush()
        for q in questions:
            db.add(Question(
                id=q.id or new_id("q"),
                batch_id=batch.id,
                bank_id=bank_id,
                document_id=document_id,
                type=q.type.value,
                score=q.score,
                difficulty=q.difficulty.value,
                difficulty_score=float(q.difficultyScore or 0),
                blueprint_json=json.dumps(q.blueprint, ensure_ascii=False) if q.blueprint else None,
                review_json=(json.dumps(q.difficultyReview, ensure_ascii=False)
                             if q.difficultyReview else None),
                stem=q.stem,
                options_json=(json.dumps([o.model_dump() for o in q.options], ensure_ascii=False)
                              if q.options else None),
                answer=q.answer,
                analysis=q.analysis,
                knowledge_point=q.knowledgePoint or None,
                source_mode=params.source_mode,
                created_by=user_id,
            ))
        db.flush()
        if run is not None:
            run.complete_in_transaction(db, batch.id)
        committing = True
        db.commit()
    except BaseException as exc:
        rolled_back = rollback_business(db)
        if run is not None:
            if committing or not rolled_back:
                run.unknown()
            elif not isinstance(exc, Exception):
                run.unknown(RunErrorCode.EXECUTION_INTERRUPTED)
            else:
                run.fail(RunErrorCode.PERSISTENCE_ERROR)
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
    bank_id = body.bank_id or body.kb_id
    document_id = body.document_id or body.doc_id
    if not bank_id or not document_id:
        raise ValueError("构造出题参数需要题库与文档标识")
    return GenerateParams(
        kb_id=bank_id,
        doc_id=document_id,
        types=[TypeCount(type=QuestionType(t.type), count=t.count) for t in body.types],
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


@trace_run("parameterized", run_id_kwarg="run_id")
def run_generation_task(
    task_id: str, user_id: str, api_key: str, body: GenerateStartBody,
    mode: str = "parametric", *, run_id: str | None = None,
) -> None:
    """后台任务：HyDE → 混合检索 → 生成 → 落库 → 更新 Redis 进度到完成。"""
    params = build_params(body)
    run = GenerationRun(
        RunEntrypoint.PARAMETERIZED, user_id, params.kb_id, params.doc_id,
        task_id=task_id, run_id=run_id,
    )
    with run.observe():
        r = cache.get_redis()
        try:
            run.begin(params)
            _write_progress(task_id, 2, "准备生成")

            # HyDE（有 scope 且有密钥时）
            hyde_text = hyde.get_hyde(
                r, params.kb_id, params.doc_id, body.scope, body.difficulty, api_key
            )
            if body.scope and hyde_text:
                _write_progress(task_id, 5, "已生成假设文档（HyDE），正在混合检索")

            doc_name = body.doc_name or ""
            if not doc_name:
                db = SessionLocal()
                try:
                    from app.models import Document

                    d = db.get(Document, params.doc_id)
                    doc_name = d.name if d else ""
                finally:
                    db.close()

            questions = question_gen.generate_questions(
                params,
                doc_name,
                scope=body.scope or None,
                existing_stems=body.existing_stems,
                progress_cb=lambda p, s: _write_progress(task_id, p, s),
                api_key=api_key,
                hyde_text=hyde_text,
            )

            db = SessionLocal()
            try:
                # 中间件：查重 → 难度评分与重出 → 生成解析，通过后才落库并交给预览
                questions, stats = question_review.review_questions(
                    db, user_id, questions, params, doc_name, api_key, hyde_text,
                    progress=lambda p, s: _write_progress(task_id, p, s),
                )
                if stats.summary():
                    logger.info("[gen:%s] 中间件：%s", task_id, stats.summary())
                batch = persist_batch(
                    db, user_id, params.kb_id, params.doc_id, mode, params, hyde_text, questions,
                    run=run,
                )
                payload = [q.model_dump() for q in questions]
                r.hset(_task_key(task_id), mapping={
                    "progress": 100, "stage": "生成完成", "status": "done",
                    "done": "1", "batch_id": batch.id,
                    "questions": json.dumps(payload, ensure_ascii=False),
                    "review": json.dumps({
                        "duplicates": stats.duplicates,
                        "repaired": stats.repaired,
                        "regenerated": stats.regenerated,
                        "solved": stats.solved,
                    }, ensure_ascii=False),
                })
                r.expire(_task_key(task_id), settings.generate_task_ttl_seconds)
            finally:
                db.close()
        except NeedConfirmError as exc:
            run.fail(RunErrorCode.NEED_CONFIRM)
            type_label = next(
                (label for label in question_gen.TYPE_LABELS.values() if label == exc.type_label),
                "材料",
            )
            r.hset(_task_key(task_id), mapping={
                "status": "failed", "done": "1",
                "error": json.dumps({
                    "kind": "need_confirm",
                    "message": f"{type_label}原题仅 {exc.available} 道，不足 {exc.requested} 道",
                    "available": exc.available, "requested": exc.requested,
                }, ensure_ascii=False),
            })
        except Exception as exc:
            run.fail(error_code(exc))
            r.hset(_task_key(task_id), mapping={
                "status": "failed", "done": "1",
                "error": json.dumps({"message": llm.friendly_error(exc)}, ensure_ascii=False),
            })
        finally:
            # 释放同用户生成锁
            r.delete(cache.PREFIX_GEN_LOCK.format(user_id=user_id))


def read_task(task_id: str, user_id: str | None = None) -> dict | None:
    """读任务进度；user_id 不匹配视为不存在。"""
    r = cache.get_redis()
    data = r.hgetall(_task_key(task_id))
    if not data:
        return None
    if user_id and data.get("user_id") and data["user_id"] != user_id:
        return None
    error = json.loads(data["error"]) if data.get("error") else None
    questions = json.loads(data["questions"]) if data.get("questions") else []
    return {
        "progress": int(data.get("progress", 0)),
        "stage": data.get("stage", ""),
        "review": json.loads(data["review"]) if data.get("review") else None,
        "done": data.get("done") == "1" or data.get("status") in ("done", "failed"),
        "batch_id": data.get("batch_id"),
        "questions": questions,
        "error": error,
    }


def acquire_lock(user_id: str) -> bool:
    return bool(cache.get_redis().set(
        cache.PREFIX_GEN_LOCK.format(user_id=user_id), "1", nx=True, ex=60,
    ))

"""管理员模型配置与索引重建：保存草稿，生成新索引，原子切换活动版本。"""
from dataclasses import replace
import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.db import SessionLocal
from app.errors import AppError
from app.models import Bank, Document, DocumentChunk, RagSetting
from app.schemas.rag_settings import (
    ActiveSettings, PendingSettings, RagSettingsBody, RagSettingsResult,
    RebuildStatus, ServiceTestBody, ServiceTestResult, VectorStoreStatus,
)
from app.services.model_settings import mask
from app.services.rag_runtime import (
    RuntimeSnapshot, decode_config, use_snapshot,
)

logger = logging.getLogger(__name__)
BUSY_STATUSES = ("queued", "running")


def _lock_settings(db: Session) -> RagSetting:
    """与资料变更共用 SQL 写锁，将重建预检和状态发布串行化。"""
    if db.get_bind().dialect.name == "sqlite":
        db.execute(sqlite_insert(RagSetting).values(id=1).on_conflict_do_nothing(
            index_elements=["id"]
        ))
    elif db.get(RagSetting, 1) is None:
        db.add(RagSetting(id=1))
        db.flush()
    db.execute(update(RagSetting).where(RagSetting.id == 1).values(
        mutation_epoch=RagSetting.mutation_epoch + 1
    ))
    row = db.get(RagSetting, 1, populate_existing=True)
    if row is None:
        raise AppError("RAG_SETTINGS_UNAVAILABLE", "系统配置暂不可用", 503)
    return row


def _check_mutation_status(row: RagSetting | None) -> None:
    if row is not None and row.rebuild_status in BUSY_STATUSES:
        raise AppError("RAG_REBUILD_BUSY", "系统正在重建索引，请稍后再修改题库资料", 409)


def precheck_mutations_allowed(db: Session) -> None:
    """只读预检保留重建忙碌错误的优先级；不代替后续写锁内门禁。"""
    _check_mutation_status(db.get(RagSetting, 1, populate_existing=True))


def assert_mutations_allowed(db: Session) -> RuntimeSnapshot:
    """锁定资料变更门禁并返回锁内活动快照；重建期间拒绝资料变更。"""
    row = _lock_settings(db)
    _check_mutation_status(row)
    return RuntimeSnapshot(decode_config(row.active_json), row.generation)


def _assert_editable(row: RagSetting, revision: int) -> None:
    if row.rebuild_status in BUSY_STATUSES:
        raise AppError("RAG_REBUILD_BUSY", "索引重建中，请等待完成后再修改配置", 409)
    if row.revision != revision:
        raise AppError("RAG_SETTINGS_CONFLICT", "配置已被更新，请重新读取后再操作", 409)


def _has_key(key: str | None) -> bool:
    from app.services.rag.embeddings import default_key_configured

    return bool(key) or default_key_configured()


def read_settings(db: Session) -> RagSettingsResult:
    """仅返回活动配置、待应用配置、凭据掩码及系统运行状态。"""
    from app.services.rag import vectorstore

    row = db.get(RagSetting, 1, populate_existing=True)
    active = decode_config(row.active_json if row else None)
    pending = decode_config(row.pending_json) if row and row.pending_json else None
    path = Path(settings.chroma_dir)
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        vectorstore.check_health()
        store = VectorStoreStatus(path=str(path.resolve()), available=True, message="Chroma 可用")
    except vectorstore.VectorStoreError as exc:
        store = VectorStoreStatus(
            path=str(path.resolve()), available=False, message=str(exc)
        )
    return RagSettingsResult(
        active=ActiveSettings(
            embedding_model=active.embedding_model,
            embedding_base_url=active.embedding_base_url,
            embedding_key_configured=_has_key(active.embedding_api_key),
            embedding_key_masked=mask(active.embedding_api_key),
            rerank_model=active.rerank_model,
            rerank_base_url=active.rerank_base_url,
            rerank_key_configured=_has_key(active.rerank_api_key),
            rerank_key_masked=mask(active.rerank_api_key),
        ),
        pending=PendingSettings(
            embedding_model=pending.embedding_model,
            embedding_base_url=pending.embedding_base_url,
            embedding_key_configured=_has_key(pending.embedding_api_key),
            embedding_key_masked=mask(pending.embedding_api_key),
        ) if pending else None,
        vector_store=store,
        rebuild=RebuildStatus.model_validate({
            "status": row.rebuild_status if row else "idle",
            "progress": row.rebuild_progress if row else 0,
            "stage": row.rebuild_stage if row else "尚未重建",
            "error": row.rebuild_error if row else None,
        }),
        revision=row.revision if row else 0,
    )


def save_settings(db: Session, body: RagSettingsBody) -> RagSettingsResult:
    """模型或地址变化仅写待应用值；凭据单独更新和重排变更供后续请求使用。"""
    row = _lock_settings(db)
    _assert_editable(row, body.revision)
    active = decode_config(row.active_json)
    pending = decode_config(row.pending_json) if row.pending_json else active
    embedding_key = body.embedding_api_key.get_secret_value().strip() if body.embedding_api_key else ""
    rerank_key = body.rerank_api_key.get_secret_value().strip() if body.rerank_api_key else ""
    embedding_changed = (
        body.embedding_model != active.embedding_model
        or body.embedding_base_url != active.embedding_base_url
    )
    active = replace(
        active, rerank_model=body.rerank_model, rerank_base_url=body.rerank_base_url,
        rerank_api_key=rerank_key or active.rerank_api_key,
    )
    if embedding_changed:
        candidate = replace(
            active, embedding_model=body.embedding_model,
            embedding_base_url=body.embedding_base_url,
            embedding_api_key=embedding_key or pending.embedding_api_key,
        )
        row.pending_json = candidate.serialize()
    else:
        active = replace(active, embedding_api_key=embedding_key or active.embedding_api_key)
        row.pending_json = None
    row.active_json = active.serialize()
    row.revision += 1
    row.rebuild_status = "idle"
    row.rebuild_progress = 0
    row.rebuild_stage = "配置已保存，等待重建应用" if row.pending_json else "配置已保存并生效"
    row.rebuild_error = None
    db.commit()
    return read_settings(db)


def test_service(db: Session, body: ServiceTestBody) -> ServiceTestResult:
    """测试草稿，不落库；服务错误统一脱敏。"""
    from app.services.rag import embeddings, rerank

    row = db.get(RagSetting, 1)
    active = decode_config(row.active_json if row else None)
    if body.service == "embedding":
        source = decode_config(row.pending_json) if row and row.pending_json else active
        config = replace(
            active, embedding_model=body.model, embedding_base_url=body.base_url,
            embedding_api_key=(body.api_key.get_secret_value().strip() if body.api_key else "")
            or source.embedding_api_key,
        )
    else:
        config = replace(
            active, rerank_model=body.model, rerank_base_url=body.base_url,
            rerank_api_key=(body.api_key.get_secret_value().strip() if body.api_key else "")
            or active.rerank_api_key,
        )
    try:
        with use_snapshot(RuntimeSnapshot(config)):
            if body.service == "embedding":
                if not embeddings.embed_texts(["模型连接检查"]):
                    raise ValueError("empty embedding")
            elif not rerank.rerank("模型连接检查", ["模型连接检查"], top_n=1):
                raise ValueError("empty rerank")
    except (embeddings.EmbeddingError, rerank.RerankError, ValueError) as exc:
        raise AppError("RAG_SERVICE_UNAVAILABLE", "连接测试失败，请检查模型、地址与凭据", 400) from exc
    return ServiceTestResult(message="连接测试通过，本次测试未保存配置")


def queue_rebuild(db: Session, revision: int) -> str:
    """锁定待应用配置并拒绝与尚未完成的资料入库同时重建。"""
    row = _lock_settings(db)
    _assert_editable(row, revision)
    if not row.pending_json:
        raise AppError("RAG_NO_PENDING_CONFIG", "没有需要重建应用的配置", 409)
    unfinished = db.query(Document.id).join(Bank, Bank.id == Document.bank_id).filter(
        Bank.status == "active", Document.status.notin_(("ready", "failed"))
    ).first()
    if unfinished:
        raise AppError("RAG_INGESTION_BUSY", "尚有资料入库中，请等待完成后再重建", 409)
    job_id = uuid4().hex[:16]
    row.rebuild_id = job_id
    row.rebuild_status = "queued"
    row.rebuild_progress = 0
    row.rebuild_stage = "重建任务已提交，旧索引继续提供服务"
    row.rebuild_error = None
    row.revision += 1
    db.commit()
    return job_id


def run_rebuild(job_id: str) -> None:
    """复用 ready 资料的 SQL 文本切片，完成所有新集合后一次提交活动指针。"""
    from app.services.rag import embeddings, vectorstore
    from app.services.rag.chunking import Chunk

    with SessionLocal() as db:
        try:
            row = db.get(RagSetting, 1)
            if not row or row.rebuild_id != job_id or row.rebuild_status != "queued":
                return
            active = decode_config(row.active_json)
            pending = decode_config(row.pending_json)
            candidate = replace(
                active, embedding_model=pending.embedding_model,
                embedding_base_url=pending.embedding_base_url,
                embedding_api_key=pending.embedding_api_key,
            )
            row.rebuild_status = "running"
            row.rebuild_stage = "正在使用已有文本切片重建向量，不重复 OCR"
            db.commit()
            docs = db.query(Document).join(Bank, Bank.id == Document.bank_id).filter(
                Bank.status == "active", Document.status == "ready"
            ).order_by(Document.bank_id, Document.id).all()
            total = sum(doc.chunk_count for doc in docs)
            completed = 0
            dimension: int | None = None
            with use_snapshot(RuntimeSnapshot(candidate, job_id)):
                vectorstore.check_health()
                # 即使暂无资料，也先确认新模型能返回向量再激活。
                probe = embeddings.embed_texts(["索引模型连接检查"])
                if len(probe) != 1 or not probe[0]:
                    raise ValueError("embedding probe invalid")
                dimension = len(probe[0])
                for doc in docs:
                    chunks = db.query(DocumentChunk).filter(
                        DocumentChunk.document_id == doc.id
                    ).order_by(DocumentChunk.chunk_index).all()
                    if not chunks or len(chunks) != doc.chunk_count:
                        raise ValueError("ready document chunks inconsistent")
                    for offset in range(0, len(chunks), 32):
                        batch = chunks[offset:offset + 32]
                        vectors = embeddings.embed_texts([chunk.text for chunk in batch])
                        if (len(vectors) != len(batch)
                                or any(len(vector) != dimension for vector in vectors)):
                            raise ValueError("embedding dimension changed")
                        vectorstore.add_chunks(
                            doc.bank_id, doc.id, doc.name,
                            [Chunk(text=chunk.text, meta={
                                "chunk_type": chunk.chunk_type or "general",
                                "section": chunk.section or "",
                                "chunk_index": chunk.chunk_index,
                            }) for chunk in batch], vectors,
                            chunk_ids=[chunk.id for chunk in batch],
                        )
                        completed += len(batch)
                        row.rebuild_progress = min(99, int(100 * completed / max(total, 1)))
                        row.rebuild_stage = f"正在重建向量（{completed}/{total} 个片段）"
                        db.commit()
            # 只切换配置指针，旧集合保留，已在途检索继续使用其快照。
            db.refresh(row)
            if row.rebuild_id != job_id or row.rebuild_status != "running":
                raise ValueError("rebuild state changed")
            row.active_json = candidate.serialize()
            row.generation = job_id
            row.pending_json = None
            row.rebuild_status = "succeeded"
            row.rebuild_progress = 100
            row.rebuild_stage = "新索引已完成，配置已切换生效"
            row.rebuild_error = None
            row.revision += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("索引重建失败，旧配置继续服务，异常类型：%s", type(exc).__name__)
            row = db.get(RagSetting, 1, populate_existing=True)
            if row and row.rebuild_id == job_id and row.rebuild_status in BUSY_STATUSES:
                row.rebuild_status = "failed"
                row.rebuild_stage = "索引重建失败，旧配置和旧索引继续提供服务"
                row.rebuild_error = "请检查向量服务、Chroma 和已解析资料后重试"
                row.revision += 1
                db.commit()


def recover_interrupted_rebuild() -> None:
    """当前单 worker 启动时释放上次进程中断的重建，不切换活动索引。"""
    with SessionLocal() as db:
        row = db.get(RagSetting, 1)
        if row and row.rebuild_status in BUSY_STATUSES:
            row.rebuild_status = "failed"
            row.rebuild_stage = "服务重启，重建已中断；旧索引继续提供服务"
            row.rebuild_error = "请重新启动重建任务"
            row.revision += 1
            db.commit()

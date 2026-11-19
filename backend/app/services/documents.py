"""文档入库管线：解析（扫描件走 MinerU OCR）→ 切片 → jieba 分词 → FTS5/SQLite → bge-m3 → Chroma。

状态机：uploaded → parsing → ocr → chunking → embedding → ready / failed
进度同时写 Redis（ingest:task:{document_id}）与 documents 行，前端轮询文档详情接口。
"""
import logging
import math
import time
from pathlib import Path

import httpx
from fastapi import BackgroundTasks
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app import local_secrets
from app.config import BASE_DIR, settings
from app.db import SessionLocal
from app.deps import refresh_bank_access, require_bank_admin
from app.errors import AppError
from app.models import Document, DocumentChunk, User
from app.models.base import new_id
from app.services import cache, mineru
from app.services.rag_settings import assert_mutations_allowed
from app.services.rag_runtime import current_snapshot, with_snapshot
from app.services.notifications import notify_bank_ingest_done
from app.services.parsing.base import ParsedBlock, get_parser
from app.services.rag import embeddings, fts, vectorstore
from app.services.parsing.ocr_textbook import parse_ocr_textbook
from app.services.rag.chunking import Chunk, chunk_blocks
from app.services.rag.tokenizer import tokenize

logger = logging.getLogger("app.documents")

# 允许上传的格式（扩展名 → 展示格式）
UPLOAD_FORMATS = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".xlsx": "XLSX",
    ".md": "MD",
    ".markdown": "MD",
    ".txt": "TXT",
}


def estimate_eta_minutes(filename: str, content: bytes) -> int:
    """按页数/体积粗估入库耗时（分钟），仅用于提示文案，不承诺精确。"""
    suffix = Path(filename).suffix.lower()
    size_mb = max(len(content) / 1048576, 0.1)
    if suffix == ".pdf":
        try:
            import pymupdf

            with pymupdf.open(stream=content, filetype="pdf") as doc:
                pages = doc.page_count
            return max(2, math.ceil(pages / 40))
        except Exception:
            return max(1, math.ceil(size_mb / 2))
    return max(1, math.ceil(size_mb / 4))


SIMPLIFIED_SUFFIX = "_知识点简化版"


def original_upload_path(doc: Document) -> dict | None:
    """被简化改写为 MD 的扫描件，其原始 PDF 固定存放在 uploads/{bank}/{doc_id}.pdf。"""
    if doc.format != "MD" or not doc.name.endswith(f"{SIMPLIFIED_SUFFIX}.md"):
        return None
    p = settings.upload_path() / doc.bank_id / f"{doc.id}.pdf"
    if not p.exists():
        return None
    try:
        rel = p.relative_to(BASE_DIR).as_posix()
    except ValueError:
        rel = p.as_posix()
    stem = Path(doc.name).stem.replace(SIMPLIFIED_SUFFIX, "")
    return {"rel": rel, "name": f"{stem}.pdf"}


def queue_upload(
    db: Session,
    background: BackgroundTasks,
    bank_id: str,
    uploader_id: str,
    filename: str,
    content: bytes,
    mineru_token: str | None,
    *,
    actor: User | None = None,
) -> dict:
    """门禁内重新授权后保存文件与文档；失败回滚并移除未登记原件。"""
    expected_actor = _mutation_actor(db, uploader_id, actor)
    assert_mutations_allowed(db)
    require_bank_admin(refresh_bank_access(db, *expected_actor, bank_id))
    suffix = Path(filename or "").suffix.lower()
    if suffix not in UPLOAD_FORMATS:
        raise AppError(
            "UNSUPPORTED_FORMAT",
            f"不支持的文件格式 {suffix or '(无扩展名)'}，目前支持 PDF/DOCX/XLSX/MD/TXT",
            status_code=400,
        )
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise AppError("DOCUMENT_TOO_LARGE", f"文件超过 {settings.max_upload_mb} MB 上限", status_code=422)
    if not content:
        raise AppError("EMPTY_FILE", "文件内容为空", status_code=400)

    doc_id = new_id("doc")
    store_dir = settings.upload_path() / bank_id
    store_path = store_dir / f"{doc_id}{suffix}"
    # 存路径：位于 backend 目录内时存相对路径，否则存绝对路径（便于整体迁移与自定义目录）
    try:
        rel_path = store_path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        rel_path = store_path.as_posix()

    doc = Document(
        id=doc_id,
        bank_id=bank_id,
        name=filename or f"{doc_id}{suffix}",
        format=UPLOAD_FORMATS[suffix],
        size_bytes=len(content),
        storage_path=rel_path,
        status="uploaded",
        stage="已上传，等待解析",
        uploader_id=uploader_id,
    )
    try:
        store_dir.mkdir(parents=True, exist_ok=True)
        store_path.write_bytes(content)
        db.add(doc)
        db.commit()
    except Exception:
        db.rollback()
        store_path.unlink(missing_ok=True)
        raise

    background.add_task(run_ingestion, doc_id, mineru_token)
    return {
        "document_id": doc_id,
        "name": doc.name,
        "status": doc.status,
        "stage": doc.stage,
        "progress": 0,
        "eta_minutes": estimate_eta_minutes(doc.name, content),
    }


def _mutation_actor(db: Session, user_id: str, actor: User | None) -> tuple[str, int]:
    """进入门禁前保留原认证版本，避免刷新账号后接受并发撤销的新版本。"""
    user = actor if actor is not None else db.get(User, user_id)
    if user is None or user.id != user_id:
        raise AppError("SESSION_REVOKED", "认证状态已变更，请重新登录", 401)
    return user.id, user.auth_version


def _set_stage(db: Session, doc: Document, status: str, stage: str, progress: int, **fields) -> None:
    """SQL 是状态真相；进度缓存不可用时仍允许调度和处理继续。"""
    doc.status = status
    doc.stage = stage
    doc.progress = max(0, min(100, progress))
    for k, v in fields.items():
        setattr(doc, k, v)
    db.commit()
    try:
        r = cache.get_redis()
        key = cache.PREFIX_INGEST_TASK.format(document_id=doc.id)
        r.hset(key, mapping={"status": status, "stage": stage, "progress": doc.progress})
        r.expire(key, settings.ingest_task_ttl_seconds)
    except RedisError as exc:
        logger.warning("Progress cache failure type=%s code=PROGRESS_CACHE_UNAVAILABLE",
                       type(exc).__name__)


def _fail(db: Session, doc: Document, message: str, ocr_error: str | None = None) -> None:
    if doc.ocr_status == "running":
        doc.ocr_status = "failed"
        doc.ocr_error = ocr_error or message
    _set_stage(db, doc, "failed", f"失败：{message}", 100, error_message=message)
    try:
        notify_bank_ingest_done(db, doc, ok=False, message=message)
    except Exception:
        pass  # 通知失败不影响状态落库


def _ocr_failure(exc: Exception) -> tuple[str, str]:
    """仅依据结构化异常分类；MinerU 文本可能含签名 URL，不解析或回显。"""
    cause: BaseException | None = exc
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, mineru.MinerUError) and (
            cause.operation != "request" or cause.provider_code is not None
            or cause.http_status is not None or cause.reason != "response"
        ):
            code = "OCR_RESPONSE"
            if cause.http_status in (401, 403) or cause.provider_code in ("A0202", "A0211"):
                code = "OCR_AUTHENTICATION"
            elif cause.http_status == 429 or cause.provider_code in ("-60009", "-60018"):
                code = "OCR_RATE_LIMIT"
            elif cause.reason == "timeout" or cause.http_status in (408, 504):
                code = "OCR_TIMEOUT"
            elif cause.reason == "connection":
                code = "OCR_CONNECTION"
            return code, cause.diagnostic()
        if isinstance(cause, PermissionError):
            return "OCR_PERMISSION", "OCR 解析失败：访问权限不足，请联系管理员检查文件与服务权限"
        if isinstance(cause, httpx.HTTPStatusError):
            status = cause.response.status_code
            if status in (401, 403):
                return "OCR_AUTHENTICATION", "OCR 解析失败：鉴权或权限不足，请检查 MinerU Token 与服务权限"
            if status in (408, 504):
                return "OCR_TIMEOUT", "OCR 解析超时，请稍后重新解析或检查文件页数限制"
            if status == 429:
                return "OCR_RATE_LIMIT", "OCR 服务限流，请稍后重新解析并检查服务额度"
            return "OCR_RESPONSE", "OCR 服务返回异常，请稍后重试并检查文件格式、大小与页数限制"
        if isinstance(cause, (httpx.TimeoutException, TimeoutError)):
            return "OCR_TIMEOUT", "OCR 解析超时，请稍后重新解析或检查文件页数限制"
        if isinstance(cause, (httpx.RequestError, ConnectionError)):
            return "OCR_CONNECTION", "无法连接 OCR 服务，请稍后重试或联系管理员检查网络连接"
        cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
    return "OCR_FAILED", "OCR 解析失败，请检查 MinerU Token、文件格式、大小与页数限制后重新解析"


def _purge_chunks(db: Session, doc: Document) -> None:
    """重新解析前清空旧 chunk、FTS 行与向量。"""
    # 外部存储失败时保留 SQL/FTS，避免尚未进入解析就丢失旧切片。
    vectorstore.delete_document_chunks(doc.bank_id, doc.id)
    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
    fts.delete_document(db, doc.id)
    db.commit()


def requeue_document(db: Session, doc: Document, *, actor: User | None = None) -> None:
    """门禁内刷新权限和文档状态，再重置上轮处理状态及队列进度。"""
    bank_id, doc_id = doc.bank_id, doc.id
    expected_actor = _mutation_actor(db, actor.id if actor is not None else doc.uploader_id, actor)
    assert_mutations_allowed(db)
    require_bank_admin(refresh_bank_access(db, *expected_actor, bank_id))
    current = db.get(Document, doc_id, populate_existing=True)
    if current is None or current.bank_id != bank_id:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在或已被删除", 404)
    doc = current
    if doc.status not in ("failed", "ready"):
        raise AppError("BAD_STATE", "仅失败或已完成的文档可重新解析", 400)
    original = original_upload_path(doc)
    if original is not None:
        doc.format = "PDF"
        doc.storage_path = original["rel"]
        doc.name = original["name"]
        original_path = Path(original["rel"])
        if not original_path.is_absolute():
            original_path = BASE_DIR / original_path
        doc.size_bytes = original_path.stat().st_size
    _set_stage(
        db, doc, "uploaded", "已重新排队，等待解析", 0,
        error_message=None, chunk_count=0, ocr_status=None, ocr_error=None,
        ocr_task_id=None, ocr_result_path=None, text_source=None,
        page_count=None, is_scanned=False,
    )


@with_snapshot
def run_ingestion(
    document_id: str, mineru_token: str | None = None,
) -> None:
    """使用操作者提交时的有效凭据入库；未提供个人凭据时使用服务端默认。"""
    t0 = time.monotonic()

    def _elapsed() -> str:
        return f"{time.monotonic() - t0:.0f}s"

    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        bank_id, doc_id = doc.bank_id, doc.id
        file_path = Path(doc.storage_path)
        if not file_path.is_absolute():
            file_path = BASE_DIR / file_path
        if not file_path.exists():
            _fail(db, doc, "源文件不存在")
            return

        _purge_chunks(db, doc)

        # ---------- 1. 解析（PDF 先做扫描件检测） ----------
        _set_stage(db, doc, "parsing", "正在解析文档", 10, error_message=None)
        blocks: list[ParsedBlock]
        if doc.format == "PDF":
            is_scanned, page_count = mineru.detect_scanned_pdf(file_path)
            doc.page_count = page_count
            doc.is_scanned = is_scanned
            db.commit()
            if is_scanned:
                # ---------- 2. 扫描件：MinerU OCR ----------
                _set_stage(db, doc, "ocr", f"MinerU 正在识别（共 {page_count} 页）", 20, ocr_status="running")
                result_dir = settings.ocr_path() / doc_id
                markdown = mineru.read_cached_markdown(file_path, result_dir)
                if markdown is None:
                    token = mineru_token or local_secrets.MINERU_DEFAULT_TOKEN
                    if not token:
                        _fail(db, doc, "未配置 MinerU Token，无法解析扫描版 PDF",
                              ocr_error="token missing")
                        return

                    def _ocr_progress(done: int, total: int) -> None:
                        pct = 20 + int(25 * done / max(1, total))
                        _set_stage(db, doc, "ocr",
                                   f"MinerU 正在识别（{done}/{total} 片，共 {page_count} 页）", pct)

                    try:
                        markdown, _ = mineru.extract_pdf(token, file_path, result_dir, _ocr_progress)
                    except mineru.MinerUError as exc:
                        code, message = _ocr_failure(exc)
                        logger.warning("Ingestion failure document=%s type=%s code=%s detail=%s",
                                       doc.id, type(exc).__name__, code, message)
                        _fail(db, doc, message, ocr_error=message)
                        return

                _set_stage(db, doc, "chunking", "正在整理 OCR 原文", 45,
                           ocr_status="done", text_source="ocr", ocr_task_id="local",
                           ocr_result_path=str(result_dir))
                blocks = parse_ocr_textbook(markdown, result_dir, page_count)
            else:
                doc.ocr_status = "not_needed"
                blocks = get_parser(file_path).parse(file_path)
                _set_stage(db, doc, "chunking", "解析完成，正在切片", 40, text_source="native")
        else:
            doc.ocr_status = "not_needed"
            blocks = get_parser(file_path).parse(file_path)
            _set_stage(db, doc, "chunking", "解析完成，正在切片", 40, text_source="native")

        if not blocks:
            _fail(db, doc, "解析结果为空：文件内容为空或格式异常")
            return

        # ---------- 3. 切片 + 分词 + 写 SQLite/FTS5 ----------
        if doc.is_scanned and doc.format == "PDF":
            chunks = [Chunk(block.text, block.meta) for block in blocks]
        else:
            chunks = chunk_blocks(blocks)
        if not chunks:
            _fail(db, doc, "切片结果为空")
            return
        _set_stage(db, doc, "chunking", f"正在写入切片（共 {len(chunks)} 块）", 57)
        rows: list[DocumentChunk] = []
        fts_rows: list[dict] = []
        for i, c in enumerate(chunks):
            chunk_id = new_id("chunk")
            tokens = tokenize(c.text)
            rows.append(
                DocumentChunk(
                    id=chunk_id,
                    bank_id=bank_id,
                    document_id=doc_id,
                    chunk_index=i,
                    chunk_type=c.meta.get("chunk_type", "general"),
                    section=c.meta.get("section", ""),
                    text=c.text,
                    tokens=tokens,
                    char_count=len(c.text),
                    source_locations=c.meta.get("source_locations"),
                )
            )
            fts_rows.append({"chunk_id": chunk_id, "bank_id": bank_id, "document_id": doc_id, "tokens": tokens})
        db.add_all(rows)
        fts.insert_rows(db, fts_rows)
        db.commit()

        # ---------- 4. 向量化 + 写 Chroma ----------
        model = current_snapshot().config.embedding_model
        _set_stage(db, doc, "embedding", f"正在向量化（{model}，共 {len(chunks)} 块）", 60)
        vectors = embeddings.embed_texts([c.text for c in chunks])
        vectorstore.add_chunks(
            bank_id,
            doc_id,
            doc.name,
            chunks,
            vectors,
            chunk_ids=[r.id for r in rows],
        )

        _set_stage(
            db, doc, "ready", "入库完成", 100,
            chunk_count=len(chunks),
        )
        logger.info("[ingest:%s] 入库完成 总用时 %s，切片 %d 块", doc.id, _elapsed(), len(chunks))
        try:
            notify_bank_ingest_done(db, doc, ok=True, message="")
        except Exception:
            pass  # 通知失败不影响状态落库
    except Exception as exc:  # 兜底：任何异常都落到 failed，避免文档卡在中间状态
        try:
            db.rollback()
            failed_doc = db.get(Document, document_id)
            if failed_doc is not None:
                if isinstance(exc, (embeddings.EmbeddingError, vectorstore.VectorStoreError)):
                    message = str(exc)
                    code = "INGEST_RAG_UNAVAILABLE"
                elif failed_doc.ocr_status == "running":
                    code, message = _ocr_failure(exc)
                else:
                    code = "INGEST_FAILED"
                    message = "文档处理失败，请检查文件格式与内容后重新解析；仍失败请联系管理员"
                logger.warning("Ingestion failure document=%s type=%s code=%s detail=%s",
                               document_id, type(exc).__name__, code, message)
                _fail(db, failed_doc, message)
        except Exception as failure:
            logger.warning("Ingestion failure type=%s code=INGEST_FAILURE_PERSIST_FAILED",
                           type(failure).__name__)
    finally:
        db.close()

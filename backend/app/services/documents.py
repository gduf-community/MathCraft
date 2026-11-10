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
from app.errors import AppError
from app.models import Document, DocumentChunk
from app.models.base import new_id
from app.services import cache, mineru
from app.services import knowledge_simplify
from app.services.rag_settings import assert_mutations_allowed
from app.services.rag_runtime import current_snapshot, with_snapshot
from app.services.notifications import notify_bank_ingest_done
from app.services.parsing.base import ParsedBlock, get_parser
from app.services.rag import embeddings, fts, vectorstore
from app.services.rag.chunking import chunk_blocks
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
            # 扫描件走 OCR 后还要按章做 LLM 概括：OCR 约 40 页/分钟，概括约 3 分钟起
            return max(2, math.ceil(pages / 40) + 3)
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
    deepseek_api_key: str | None = None,
) -> dict:
    """保存文档、建 Document 行并投递后台入库任务；立即返回，含预计耗时。"""
    assert_mutations_allowed(db)
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
    store_dir.mkdir(parents=True, exist_ok=True)
    store_path = store_dir / f"{doc_id}{suffix}"
    store_path.write_bytes(content)
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
    db.add(doc)
    db.commit()

    background.add_task(run_ingestion, doc_id, mineru_token, deepseek_api_key=deepseek_api_key)
    return {
        "document_id": doc_id,
        "name": doc.name,
        "status": doc.status,
        "stage": doc.stage,
        "progress": 0,
        "eta_minutes": estimate_eta_minutes(doc.name, content),
    }


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


def requeue_document(db: Session, doc: Document) -> None:
    """重置上轮处理状态并同步队列进度，保留磁盘 OCR 缓存供后续复用。"""
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
    document_id: str, mineru_token: str | None = None, *, deepseek_api_key: str | None = None,
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
                token = mineru_token or local_secrets.MINERU_DEFAULT_TOKEN
                if not token:
                    _fail(db, doc, "未配置 MinerU Token，无法解析扫描版 PDF", ocr_error="token missing")
                    return
                # ---------- 2. OCR（已有缓存结果直接复用，避免重复消耗 MinerU 额度） ----------
                result_dir = settings.ocr_path() / doc_id
                cached = result_dir / "full.md"
                if cached.exists():
                    markdown = cached.read_text(encoding="utf-8", errors="ignore")
                    doc.ocr_result_path = str(result_dir)
                    doc.ocr_task_id = "local"
                    _set_stage(db, doc, "chunking", "复用已有 OCR 结果，正在生成简化知识点文档", 45, ocr_status="done", text_source="ocr")
                else:
                    def _ocr_progress(done: int, total: int) -> None:
                        """分片识别进度：首片 15 页提目录，其余分片批量识别。"""
                        pct = 20 + int(25 * done / max(1, total))
                        _set_stage(db, doc, "ocr",
                                   f"MinerU 正在识别（{done}/{total} 片，共 {page_count} 页）", pct)

                    try:
                        markdown, _ = mineru.extract_pdf(token, file_path, result_dir, _ocr_progress)
                        doc.ocr_result_path = str(result_dir)
                        doc.ocr_task_id = "local"
                        logger.info("[ingest:%s] OCR 完成 用时 %s，正文 %d 字",
                                    doc.id, _elapsed(), len(markdown))
                        _set_stage(db, doc, "chunking", "OCR 完成，正在生成简化知识点文档", 45, ocr_status="done", text_source="ocr")
                    except mineru.MinerUError as exc:
                        code, message = _ocr_failure(exc)
                        logger.warning("Ingestion failure type=%s code=%s", type(exc).__name__, code)
                        _fail(db, doc, message, ocr_error=message)
                        return

                # ---------- 2.5 简化层：OCR 全文 → 目录 → 按节定位 → 按章概括 → 简化 MD ----------
                # 题库的入库、检索、向量化对象统一为简化版知识点文档，PDF 原件仅留作重新解析源
                llm_usage: dict = {}
                simplified_path = settings.upload_path() / doc.bank_id / f"{doc.id}_simplified.md"
                simplified = ""
                simplified_ok = True
                # 重新解析时复用已生成的简化文档，避免重复消耗 LLM 额度（回退原文的产物不复用）
                if simplified_path.exists():
                    cached_md = simplified_path.read_text(encoding="utf-8", errors="ignore")
                    if cached_md.startswith("# 《") and "知识点简化版" in cached_md[:300]:
                        simplified = cached_md
                        _set_stage(db, doc, "chunking", "复用已生成的简化知识点文档，正在切片", 56)
                        logger.info("[ingest:%s] 复用简化文档 %d 字", doc.id, len(cached_md))
                try:
                    if simplified:
                        pass
                    else:
                        def _simplify_progress(done: int, total: int) -> None:
                            """按章概括进度：目录已解析，逐章生成知识点。"""
                            _set_stage(db, doc, "chunking",
                                       f"正在概括知识点（{done}/{total} 章）", 45 + int(10 * done / max(1, total)))

                        simplified, llm_usage = knowledge_simplify.build_simplified_markdown(
                            markdown, doc.name, _simplify_progress, api_key=deepseek_api_key,
                        )
                        logger.info("[ingest:%s] 简化层 token 用量: %s", doc.id, llm_usage)
                except knowledge_simplify.SimplifyServiceError as exc:
                    # LLM 服务不可用（余额不足/鉴权失败/超时）：明确失败并通知，处理后可重新解析
                    logger.warning("Ingestion failure type=%s code=SIMPLIFY_SERVICE_UNAVAILABLE",
                                   type(exc).__name__)
                    _fail(db, doc, "简化知识点文档生成失败，请检查模型服务凭据、额度与连接后重新解析")
                    return
                except Exception as exc:
                    # 内容类失败（如无法定位目录结构）：回退原文入库，保证文档可用
                    logger.warning("Ingestion failure type=%s code=SIMPLIFY_CONTENT_FALLBACK",
                                   type(exc).__name__)
                    _set_stage(db, doc, "chunking", "简化生成失败，改用 OCR 原文入库", 46)
                    simplified = markdown
                    simplified_ok = False

                logger.info("[ingest:%s] 简化文档生成完成 用时 %s", doc.id, _elapsed())
                simplified_path.parent.mkdir(parents=True, exist_ok=True)
                simplified_path.write_text(simplified, encoding="utf-8")
                if simplified_ok:
                    # 幂等：重复解析时避免后缀叠加
                    base_name = Path(doc.name).stem.replace("_知识点简化版", "")
                    doc.name = f"{base_name}_知识点简化版.md"
                    doc.format = "MD"
                    doc.size_bytes = simplified_path.stat().st_size
                    try:
                        doc.storage_path = simplified_path.relative_to(BASE_DIR).as_posix()
                    except ValueError:
                        doc.storage_path = simplified_path.as_posix()
                    db.commit()
                # 简化失败时保留原件条目（名称、格式、下载仍是 PDF），仅索引使用 OCR 文本
                _set_stage(db, doc, "chunking", "简化知识点文档生成完成，正在切片", 56, ocr_status="done", text_source="ocr")

                # OCR 结果是 Markdown，按标题切块
                blocks = get_parser(simplified_path).parse(simplified_path)
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
                logger.warning("Ingestion failure type=%s code=%s", type(exc).__name__, code)
                _fail(db, failed_doc, message)
        except Exception as failure:
            logger.warning("Ingestion failure type=%s code=INGEST_FAILURE_PERSIST_FAILED",
                           type(failure).__name__)
    finally:
        db.close()

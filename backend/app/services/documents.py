"""文档入库管线：解析（扫描件走 MinerU OCR）→ 切片 → jieba 分词 → FTS5/SQLite → bge-m3 → Chroma。

状态机：uploaded → parsing → ocr → chunking → embedding → ready / failed
进度同时写 Redis（ingest:task:{document_id}）与 documents 行，前端轮询文档详情接口。
"""
from pathlib import Path

from sqlalchemy.orm import Session

from app import local_secrets
from app.config import BASE_DIR, settings
from app.db import SessionLocal
from app.models import Document, DocumentChunk
from app.models.base import new_id
from app.services import cache, mineru
from app.services.parsing.base import ParsedBlock, get_parser
from app.services.rag import embeddings, fts, vectorstore
from app.services.rag.chunking import chunk_blocks
from app.services.rag.tokenizer import tokenize


def _set_stage(db: Session, doc: Document, status: str, stage: str, progress: int, **fields) -> None:
    doc.status = status
    doc.stage = stage
    doc.progress = max(0, min(100, progress))
    for k, v in fields.items():
        setattr(doc, k, v)
    db.commit()
    r = cache.get_redis()
    key = cache.PREFIX_INGEST_TASK.format(document_id=doc.id)
    r.hset(key, mapping={"status": status, "stage": stage, "progress": doc.progress})
    r.expire(key, settings.ingest_task_ttl_seconds)


def _fail(db: Session, doc: Document, message: str, ocr_error: str | None = None) -> None:
    doc.ocr_error = ocr_error
    _set_stage(db, doc, "failed", f"失败：{message}", 100, error_message=message)


def _purge_chunks(db: Session, doc: Document) -> None:
    """重新解析前清空旧 chunk、FTS 行与向量。"""
    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
    fts.delete_document(db, doc.id)
    db.commit()
    vectorstore.delete_document_chunks(doc.bank_id, doc.id)


def run_ingestion(document_id: str, mineru_token: str | None = None) -> None:
    """后台入库任务；MinerU Token 为空时使用系统默认。"""
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
                try:
                    result_dir = settings.ocr_path() / doc_id
                    markdown, _ = mineru.extract_pdf(token, file_path, result_dir)
                    doc.ocr_result_path = str(result_dir)
                    doc.ocr_task_id = "local"
                    _set_stage(db, doc, "chunking", "OCR 完成，正在切片", 45, ocr_status="done", text_source="ocr")
                except mineru.MinerUError as exc:
                    _set_stage(db, doc, "failed", f"OCR 失败：{exc}", 100, ocr_status="failed", ocr_error=str(exc))
                    return
                # OCR 结果是 Markdown，按标题切块
                md_tmp = settings.ocr_path() / doc_id / "full.md"
                blocks = get_parser(md_tmp).parse(md_tmp)
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
        _set_stage(db, doc, "chunking", f"正在写入切片（共 {len(chunks)} 块）", 50)
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
        _set_stage(db, doc, "embedding", f"正在向量化（bge-m3，共 {len(chunks)} 块）", 60)
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
    except Exception as exc:  # 兜底：任何异常都落到 failed，避免文档卡在中间状态
        try:
            db.rollback()
            doc = db.get(Document, document_id)
            if doc is not None:
                _fail(db, doc, f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
    finally:
        db.close()

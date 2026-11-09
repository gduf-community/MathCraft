"""文档接口：上传（异步入库）、状态轮询、重新解析、下载、删除、混合检索测试（v2 5.4）。"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.db import get_db
from app.deps import (
    BankAccess,
    get_bank_access,
    require_bank_admin,
    require_bank_super_admin,
)
from app.errors import AppError
from app.models import Document
from app.schemas.bank import SearchBody
from app.services import banks as bank_service
from app.services import documents as doc_service
from app.services.model_settings import get_effective_mineru_token

router = APIRouter(prefix="/api/banks/{bank_id}", tags=["documents"])

FORMATS = doc_service.UPLOAD_FORMATS


def _doc_payload(doc: Document) -> dict:
    return {
        "id": doc.id,
        "bank_id": doc.bank_id,
        "name": doc.name,
        "format": doc.format,
        "size_bytes": doc.size_bytes,
        "page_count": doc.page_count,
        "is_scanned": bool(doc.is_scanned),
        "status": doc.status,
        "stage": doc.stage,
        "progress": doc.progress,
        "chunk_count": doc.chunk_count,
        "ocr_status": doc.ocr_status,
        "error_message": doc.error_message,
        "created_at": doc.created_at,
    }


def _get_document(bank_id: str, document_id: str, db: Session) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.bank_id != bank_id:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在或已被删除", status_code=404)
    return doc


@router.get("/documents")
def list_documents(
    access: BankAccess = Depends(get_bank_access),
    db: Session = Depends(get_db),
):
    docs = (
        db.query(Document)
        .filter(Document.bank_id == access.bank.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [_doc_payload(d) for d in docs]


@router.post("/documents", status_code=202)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile,
    access: BankAccess = Depends(require_bank_admin),
    db: Session = Depends(get_db),
):
    """上传文档：保存文件后立即返回，解析/OCR/切片/向量化在后台进行。"""
    content = await file.read()
    result = doc_service.queue_upload(
        db, background, access.bank.id, access.member.user_id,
        file.filename or "", content,
        get_effective_mineru_token(db, access.member.user_id),
    )
    return result


@router.get("/documents/{document_id}")
def get_document_status(
    document_id: str,
    access: BankAccess = Depends(get_bank_access),
    db: Session = Depends(get_db),
):
    doc = _get_document(access.bank.id, document_id, db)
    return _doc_payload(doc)


@router.post("/documents/{document_id}/reprocess", status_code=202)
def reprocess_document(
    document_id: str,
    background: BackgroundTasks,
    access: BankAccess = Depends(require_bank_admin),
    db: Session = Depends(get_db),
):
    doc = _get_document(access.bank.id, document_id, db)
    if doc.status not in ("failed", "ready"):
        raise AppError("BAD_STATE", "仅失败或已完成的文档可重新解析", status_code=400)
    # 曾被简化改写为 MD 的扫描件：还原原始 PDF 再重新解析（OCR 结果有缓存，不重复消耗额度）
    original = doc_service.original_upload_path(doc)
    if original is not None:
        doc.format = "PDF"
        doc.storage_path = original["rel"]
        doc.name = original["name"]
    doc.status = "uploaded"
    doc.stage = "已重新排队，等待解析"
    doc.error_message = None
    db.commit()
    mineru_token = get_effective_mineru_token(db, access.member.user_id)
    background.add_task(doc_service.run_ingestion, doc.id, mineru_token)
    return {"document_id": doc.id, "status": doc.status, "stage": doc.stage, "progress": 0}


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str,
    inline: bool = False,
    access: BankAccess = Depends(get_bank_access),
    db: Session = Depends(get_db),
):
    """下载文档原件；inline=1 供前端「查看」按钮在浏览器直接打开。"""
    doc = _get_document(access.bank.id, document_id, db)
    p = Path(doc.storage_path)
    if not p.is_absolute():
        p = BASE_DIR / p
    if not p.exists():
        raise AppError("DOCUMENT_NOT_FOUND", "源文件已不存在", status_code=404)
    if inline and doc.format == "MD":
        # Markdown 以纯文本内联展示，浏览器可直接阅读
        return FileResponse(p, filename=doc.name, media_type="text/plain; charset=utf-8",
                            content_disposition_type="inline")
    return FileResponse(p, filename=doc.name, content_disposition_type="inline" if inline else "attachment")


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    access: BankAccess = Depends(require_bank_admin),
    db: Session = Depends(get_db),
):
    doc = _get_document(access.bank.id, document_id, db)
    bank_service.purge_document(db, doc)
    return None


@router.post("/search")
def search_bank(
    body: SearchBody,
    access: BankAccess = Depends(get_bank_access),
):
    """检索测试：mode=dense/sparse/hybrid/hybrid_rerank，默认完整链路。"""
    from app.services.rag import fts, retrieval, vectorstore
    from app.services.rag import embeddings

    if body.mode in ("hybrid", "hybrid_rerank"):
        result = retrieval.hybrid_retrieve(
            access.bank.id,
            body.query,
            document_id=body.document_id,
            rerank_top_k=body.top_k if body.mode == "hybrid_rerank" else None,
        )
        if body.mode == "hybrid":
            result["reranked"] = []
        # 精简 dense 字段
        result["dense"] = [{k: h[k] for k in ("chunk_id", "doc_name", "chunk_index", "distance")} | {"text": h["text"]} for h in result["dense"]]
        return result

    if body.mode == "dense":
        vec = embeddings.embed_one(body.query)
        hits = vectorstore.search(access.bank.id, vec, top_k=body.top_k, doc_id=body.document_id)
        return {"mode": "dense", "results": hits}

    # sparse
    rows = fts.search(access.bank.id, body.query, top_k=body.top_k, document_id=body.document_id)
    return {"mode": "sparse", "results": [{"chunk_id": c, "bm25": s} for c, s in rows]}

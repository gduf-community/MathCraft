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
)
from app.errors import AppError
from app.models import Document
from app.schemas.auth import ErrorResponse
from app.schemas.bank import SearchBody
from app.services import banks as bank_service
from app.services import documents as doc_service
from app.services.model_settings import get_effective_deepseek_key, get_effective_mineru_token
from app.services.rag import embeddings, vectorstore
from app.services.rag_runtime import with_snapshot
from app.services.rag_settings import assert_mutations_allowed

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
        deepseek_api_key=get_effective_deepseek_key(db, access.member.user_id),
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
    assert_mutations_allowed(db)
    doc = _get_document(access.bank.id, document_id, db)
    if doc.status not in ("failed", "ready"):
        raise AppError("BAD_STATE", "仅失败或已完成的文档可重新解析", status_code=400)
    doc_service.requeue_document(db, doc)
    mineru_token = get_effective_mineru_token(db, access.member.user_id)
    deepseek_api_key = get_effective_deepseek_key(db, access.member.user_id)
    background.add_task(
        doc_service.run_ingestion, doc.id, mineru_token, deepseek_api_key=deepseek_api_key,
    )
    return {"document_id": doc.id, "status": doc.status, "stage": doc.stage, "progress": 0}


@router.get(
    "/documents/{document_id}/download",
    response_class=FileResponse,
    responses={
        200: {
            "description": "当前 storage_path 指向的文件；inline 参数决定内联展示或附件下载",
            "headers": {
                "Content-Disposition": {
                    "description": "inline 或 attachment，附带 filename 或 filename* 文件名",
                    "schema": {"type": "string"},
                },
            },
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in (
                    "application/pdf", "text/plain",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/octet-stream",
                )
            },
        },
        401: {"model": ErrorResponse, "description": "未登录或凭据已失效"},
        403: {"model": ErrorResponse, "description": "当前账号无教学资源访问权限"},
        404: {"model": ErrorResponse, "description": "题库、文档或当前文件不存在或不可访问"},
        503: {"model": ErrorResponse, "description": "依赖服务暂不可用"},
    },
)
def download_document(
    document_id: str,
    inline: bool = False,
    access: BankAccess = Depends(get_bank_access),
    db: Session = Depends(get_db),
):
    """下载当前 storage_path 指向的产物；inline=1 供浏览器直接查看。"""
    doc = _get_document(access.bank.id, document_id, db)
    p = Path(doc.storage_path)
    if not p.is_absolute():
        p = BASE_DIR / p
    if not p.exists():
        raise AppError("DOCUMENT_NOT_FOUND", "源文件已不存在", status_code=404)
    media_types = {
        "PDF": "application/pdf",
        "MD": "text/plain; charset=utf-8",
        "TXT": "text/plain; charset=utf-8",
        "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return FileResponse(
        p, filename=doc.name, media_type=media_types.get(doc.format, "application/octet-stream"),
        content_disposition_type="inline" if inline else "attachment",
    )


@router.delete("/documents/{document_id}", status_code=204, responses={
    503: {
        "model": ErrorResponse,
        "description": "向量存储不可用或数据库写锁重试耗尽（DATABASE_BUSY）；SQL 与原件保留，可稍后重试",
    },
})
def delete_document(
    document_id: str,
    access: BankAccess = Depends(require_bank_admin),
    db: Session = Depends(get_db),
):
    doc = _get_document(access.bank.id, document_id, db)
    try:
        bank_service.purge_document(db, doc, actor=access.user)
    except vectorstore.VectorStoreError as exc:
        raise AppError("VECTOR_STORE_UNAVAILABLE", str(exc), status_code=503) from exc
    return None


@router.post("/search", responses={
    503: {"model": ErrorResponse, "description": "向量存储或嵌入服务暂不可用"},
})
@with_snapshot
def search_bank(
    body: SearchBody,
    access: BankAccess = Depends(get_bank_access),
):
    """仅检索 ready 文档；hybrid 只融合不重排，默认 hybrid_rerank 执行重排。"""
    try:
        return _search_bank(body, access)
    except vectorstore.VectorStoreError as exc:
        raise AppError("VECTOR_STORE_UNAVAILABLE", str(exc), status_code=503) from exc
    except embeddings.EmbeddingError as exc:
        raise AppError("EMBEDDING_UNAVAILABLE", str(exc), status_code=503) from exc


def _search_bank(body: SearchBody, access: BankAccess) -> dict:
    from app.services.rag import fts, retrieval
    from app.services.rag import embeddings

    if body.mode in ("hybrid", "hybrid_rerank"):
        result = retrieval.hybrid_retrieve(
            access.bank.id,
            body.query,
            document_id=body.document_id,
            rerank_top_k=body.top_k if body.mode == "hybrid_rerank" else None,
            skip_rerank=body.mode == "hybrid",
        )
        # 精简 dense 字段
        result["dense"] = [{k: h[k] for k in ("chunk_id", "doc_name", "chunk_index", "distance")} | {"text": h["text"]} for h in result["dense"]]
        return result

    if body.mode == "dense":
        vec = embeddings.embed_one(body.query)
        hits = retrieval.dense_search(
            access.bank.id, vec, top_k=body.top_k, document_id=body.document_id,
        )
        return {"mode": "dense", "results": hits}

    # sparse
    rows = fts.search(access.bank.id, body.query, top_k=body.top_k, document_id=body.document_id)
    return {"mode": "sparse", "results": [{"chunk_id": c, "bm25": s} for c, s in rows]}

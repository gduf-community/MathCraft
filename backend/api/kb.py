"""知识库路由：上传入库、文档清单、检索测试。"""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from config import settings
from services import vectorstore
from services.ingestion import ingest_file
from services.retrieval import retrieve

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.post("/upload")
async def upload(file: UploadFile = File(...), kb_id: str = Form("kb-math")):
    """上传文档并入库：解析 → 切片 → 向量化 → Chroma。"""
    suffix = Path(file.filename or "").suffix.lower()
    allowed = {".pdf", ".docx", ".xlsx", ".md", ".markdown"}
    if suffix not in allowed:
        raise HTTPException(400, f"不支持的格式 {suffix}，支持：{sorted(allowed)}")
    dest = settings.upload_path() / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        result = ingest_file(kb_id, dest, doc_name=file.filename)
    except NotImplementedError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return result


@router.get("/documents")
def documents(kb_id: str = "kb-math"):
    return vectorstore.list_documents(kb_id)


class SearchBody(BaseModel):
    kb_id: str = "kb-math"
    query: str
    top_k: int | None = None
    doc_id: str | None = None


@router.post("/search")
def search(body: SearchBody):
    """RAG 检索测试接口：返回 top-k 相关片段。"""
    try:
        return retrieve(body.kb_id, body.query, top_k=body.top_k, doc_id=body.doc_id)
    except Exception as exc:
        raise HTTPException(500, f"检索失败：{exc}") from exc

"""出题编排使用的正式知识库适配层。

出题服务只通过这里访问 MathCraft 正式知识库，避免重新引入旧的
Chroma/Ollama 入库和检索实现。
"""

from __future__ import annotations

from MathCraft.multi_user.knowledge_access import (
    list_visible_knowledge_bases,
    resolve_kb,
    resolve_kb_manifest,
)


def list_knowledge_bases() -> list[dict]:
    """返回当前用户可见的正式知识库。"""
    return list_visible_knowledge_bases()


def list_documents(kb_id: str) -> list[dict]:
    """返回正式知识库 raw 目录中的文档，doc_id 即 raw 下 POSIX 相对路径。"""
    manifest = resolve_kb_manifest(kb_id, limit=10000)
    if manifest is None or not manifest.enumerable:
        return []
    return [
        {
            "doc_id": document.name,
            "doc_name": document.name,
            "size": document.size,
            "chunks": 0,
        }
        for document in manifest.documents
    ]


def resolve_for_rag(kb_id: str):
    """解析知识库的物理目录和规范名称，供 RAGService 使用。"""
    resource = resolve_kb(kb_id, require_write=False)
    return resource


def ensure_document(kb_id: str, doc_id: str) -> str:
    """校验文档属于知识库，并返回其正式 document_key。"""
    documents = list_documents(kb_id)
    if not any(item["doc_id"] == doc_id for item in documents):
        raise ValueError(f"文档不存在或不属于知识库：{doc_id}")
    return doc_id


async def check_document(kb_id: str, doc_id: str) -> dict:
    from fastapi import HTTPException
    from MathCraft.services.rag.evidence import KnowledgeError
    from MathCraft.services.rag.service import RAGService

    try:
        resource = resolve_for_rag(kb_id)
        records = await RAGService(kb_base_dir=str(resource.base_dir)).document_status(resource.name, [doc_id])
    except HTTPException as exc:
        raise KnowledgeError("knowledge_base_unavailable", "知识库不存在或当前不可用。") from exc
    except KnowledgeError:
        raise
    except ValueError as exc:
        raise KnowledgeError("embedding_binding_unavailable", str(exc)) from exc
    record = records[0]
    if record["status"] != "ready":
        raise KnowledgeError(record["status"], "；".join(record["warnings"]))
    if record.get("completeness") != "complete":
        raise KnowledgeError("evidence_incomplete", "；".join(record["warnings"]) or "当前材料完整性尚未确认。")
    return record


__all__ = ["ensure_document", "list_documents", "list_knowledge_bases", "resolve_for_rag"]

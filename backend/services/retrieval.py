"""正式 RAG 检索适配器。

这里把 RAGService 的 sources 转换成出题 prompt 使用的稳定结构，
检索范围通过 document_keys 严格限制到用户选择的单个文档。
"""

from __future__ import annotations

from math_q_agent.services.rag.service import RAGService

from services.knowledge import ensure_document, resolve_for_rag


async def retrieve(
    kb_id: str,
    query: str,
    top_k: int = 8,
    doc_id: str | None = None,
) -> list[dict]:
    resource = resolve_for_rag(kb_id)
    document_keys = [ensure_document(kb_id, doc_id)] if doc_id else None
    result = await RAGService(kb_base_dir=str(resource.base_dir)).search(
        query=query,
        kb_name=resource.name,
        top_k=top_k,
        document_keys=document_keys,
    )
    if result.get("needs_reindex"):
        raise ValueError(result.get("answer") or "正式知识库尚未完成索引，请先重新索引")
    if result.get("error_type"):
        raise ValueError(result.get("answer") or "正式知识库检索失败")

    hits: list[dict] = []
    for source in result.get("sources", []):
        text = str(source.get("evidence_text") or source.get("content") or "").strip()
        if not text:
            continue
        document_key = str(source.get("document_key") or source.get("source") or doc_id or "")
        title = str(source.get("title") or document_key or "知识库文档")
        score = source.get("score")
        hits.append(
            {
                "text": text,
                "doc_name": title,
                "doc_id": document_key,
                "chunk_index": source.get("chunk_id", ""),
                "distance": (1 - float(score)) if isinstance(score, (int, float)) else None,
            }
        )
    return hits


__all__ = ["retrieve"]

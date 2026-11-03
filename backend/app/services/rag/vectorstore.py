"""Chroma 持久化封装。一个题库一个 collection，chunk 元数据记录在 metadata。"""
import re

import chromadb

from app.config import settings

_client: chromadb.api.ClientAPI | None = None


def get_client() -> chromadb.api.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(settings.chroma_path()))
    return _client


def safe_collection(bank_id: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", bank_id)[:50] or "default"
    return f"kb_{name}"


def get_collection(bank_id: str, create: bool = True):
    client = get_client()
    name = safe_collection(bank_id)
    if create:
        return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
    try:
        return client.get_collection(name=name)
    except Exception:
        return None


def add_chunks(
    bank_id: str,
    doc_id: str,
    doc_name: str,
    chunks: list,  # list[chunking.Chunk]
    embeddings: list[list[float]],
    chunk_ids: list[str] | None = None,
) -> None:
    if not chunks:
        return
    col = get_collection(bank_id)
    ids = chunk_ids or [f"{doc_id}_{i}" for i in range(len(chunks))]
    col.add(
        ids=ids,
        documents=[c.text for c in chunks],
        embeddings=embeddings,
        metadatas=[
            {
                "chunk_id": ids[i],
                "bank_id": bank_id,
                "doc_id": doc_id,
                "doc_name": doc_name,
                "chunk_index": i,
                "chunk_type": c.meta.get("chunk_type", "general"),
                "section": c.meta.get("section", ""),
            }
            for i, c in enumerate(chunks)
        ],
    )


def search(
    bank_id: str,
    query_embedding: list[float],
    top_k: int,
    doc_id: str | None = None,
) -> list[dict]:
    col = get_collection(bank_id, create=False)
    if col is None:
        return []
    where = {"doc_id": doc_id} if doc_id else None
    res = col.query(query_embeddings=[query_embedding], n_results=top_k, where=where)
    hits: list[dict] = []
    for i in range(len(res["ids"][0])):
        meta = res["metadatas"][0][i]
        hits.append(
            {
                "chunk_id": meta.get("chunk_id", res["ids"][0][i]),
                "text": res["documents"][0][i],
                "doc_id": meta.get("doc_id", ""),
                "doc_name": meta.get("doc_name", ""),
                "chunk_index": meta.get("chunk_index", -1),
                "chunk_type": meta.get("chunk_type", "general"),
                "section": meta.get("section", ""),
                "distance": res["distances"][0][i] if "distances" in res else None,
            }
        )
    return hits


def delete_document_chunks(bank_id: str, doc_id: str) -> None:
    col = get_collection(bank_id, create=False)
    if col is None:
        return
    try:
        col.delete(where={"doc_id": doc_id})
    except Exception:
        pass


def delete_bank_collection(bank_id: str) -> None:
    try:
        get_client().delete_collection(name=safe_collection(bank_id))
    except Exception:
        pass


def count_question_chunks(bank_id: str, doc_id: str) -> list[dict]:
    """返回文档中所有题目 chunk 的元信息，供原题数量统计。

    返回 [{section, text}]；空列表表示材料没有题号结构（无法统计）。
    """
    col = get_collection(bank_id, create=False)
    if col is None:
        return []
    data = col.get(where={"doc_id": doc_id}, include=["metadatas", "documents"])
    out: list[dict] = []
    for meta, doc_text in zip(data["metadatas"], data["documents"]):
        if meta.get("chunk_type") == "question":
            out.append({"section": meta.get("section", ""), "text": doc_text})
    return out

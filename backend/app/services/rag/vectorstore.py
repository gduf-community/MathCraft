"""Chroma 持久化封装。一个题库一个 collection，chunk 元数据记录在 metadata。"""
from collections.abc import Iterator
from contextlib import contextmanager
import logging
import re
from typing import Literal, overload

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.api.types import PyEmbedding, Where
from chromadb.errors import NotFoundError

from app.config import settings
from app.services.rag.chunking import Chunk
from app.services.rag_runtime import current_snapshot

_client: ClientAPI | None = None
logger = logging.getLogger(__name__)
Operation = Literal["init", "access", "write", "query", "read", "delete", "health"]
_MESSAGES: dict[Operation, str] = {
    "init": "向量存储初始化失败，请联系管理员检查部署状态",
    "access": "向量集合访问失败，请联系管理员检查部署状态",
    "write": "向量写入失败，请联系管理员检查存储后重新解析",
    "query": "向量检索失败，请稍后重试或联系管理员",
    "read": "向量读取失败，请稍后重试或联系管理员",
    "delete": "向量删除失败，请联系管理员检查存储后重试",
    "health": "向量存储健康检查失败，请联系管理员检查部署状态",
}


class VectorStoreError(RuntimeError):
    """向量边界错误；对外只携带安全消息与受限诊断字段。"""

    def __init__(self, operation: Operation, error_type: str, native_code: int | None = None):
        self.operation = operation
        self.error_type = error_type
        self.native_code = native_code
        message = _MESSAGES[operation]
        if native_code == 14:
            prefix = message.split("，", 1)[0]
            message = f"{prefix}：无法打开向量数据库，请联系管理员检查存储路径与临时目录权限（code 14）"
        super().__init__(message)


@contextmanager
def _operation(operation: Operation) -> Iterator[None]:
    """将底层错误归类，只记录异常类型和数值错误码，不记录原始异常。"""
    try:
        yield
    except VectorStoreError:
        raise
    except Exception as exc:
        match = re.search(r"\bcode\s*[:=]\s*(\d{1,5})\b", str(exc), re.IGNORECASE)
        native_code = int(match.group(1)) if match else None
        error = VectorStoreError(operation, type(exc).__name__, native_code)
        logger.warning("Chroma failure operation=%s type=%s native_code=%s",
                       operation, error.error_type, native_code)
        raise error from exc


def get_client() -> ClientAPI:
    """惰性初始化持久客户端，初始化失败后允许后续重试。"""
    global _client
    if _client is None:
        with _operation("init"):
            _client = chromadb.PersistentClient(path=str(settings.chroma_path()))
    return _client


def check_health() -> None:
    """检查原生存储可用性，健康检查故障沿用安全错误边界。"""
    with _operation("health"):
        get_client().heartbeat()


def safe_collection(bank_id: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", bank_id)[:50] or "default"
    generation = current_snapshot().generation
    return f"kb_{name}" + (f"_{generation}" if generation else "")


@overload
def get_collection(bank_id: str, create: Literal[True] = True) -> Collection: ...


@overload
def get_collection(bank_id: str, create: Literal[False]) -> Collection | None: ...


def get_collection(bank_id: str, create: bool = True) -> Collection | None:
    """取得集合；只有只读查找的原生 NotFound 表示集合不存在。"""
    client = get_client()
    name = safe_collection(bank_id)
    with _operation("access"):
        if create:
            return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
        try:
            return client.get_collection(name=name)
        except NotFoundError:
            return None


def add_chunks(
    bank_id: str,
    doc_id: str,
    doc_name: str,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    chunk_ids: list[str] | None = None,
) -> None:
    """写入切片及业务标识，向量或元数据写入失败时上抛安全错误。"""
    if not chunks:
        return
    col = get_collection(bank_id)
    ids = chunk_ids or [f"{doc_id}_{i}" for i in range(len(chunks))]
    vectors: list[PyEmbedding] = [vector for vector in embeddings]
    with _operation("write"):
        col.add(
            ids=ids,
            documents=[c.text for c in chunks],
            embeddings=vectors,
            metadatas=[
                {
                    "chunk_id": ids[i],
                    "bank_id": bank_id,
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                    "chunk_index": c.meta.get("chunk_index", i),
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
    """查询文档切片；不存在的集合返回空列表，存储故障上抛。"""
    col = get_collection(bank_id, create=False)
    if col is None:
        return []
    where: Where | None = {"doc_id": doc_id} if doc_id else None
    with _operation("query"):
        res = col.query(query_embeddings=[query_embedding], n_results=top_k, where=where)
        metadata, documents, distances = res["metadatas"], res["documents"], res["distances"]
        if metadata is None or documents is None:
            raise ValueError("missing query fields")
        hits: list[dict] = []
        for i in range(len(res["ids"][0])):
            meta = metadata[0][i]
            hits.append(
                {
                    "chunk_id": meta.get("chunk_id", res["ids"][0][i]),
                    "text": documents[0][i],
                    "doc_id": meta.get("doc_id", ""),
                    "doc_name": meta.get("doc_name", ""),
                    "chunk_index": meta.get("chunk_index", -1),
                    "chunk_type": meta.get("chunk_type", "general"),
                    "section": meta.get("section", ""),
                    "distance": distances[0][i] if distances is not None else None,
                }
            )
        return hits


def delete_document_chunks(bank_id: str, doc_id: str) -> None:
    """删除文档向量；集合不存在可幂等返回，真实删除失败必须上抛。"""
    col = get_collection(bank_id, create=False)
    if col is None:
        return
    with _operation("delete"):
        col.delete(where={"doc_id": doc_id})


def delete_bank_collection(bank_id: str) -> None:
    """删除整个集合，只有原生 NotFound 可视作幂等成功。"""
    client = get_client()
    name = safe_collection(bank_id)
    with _operation("delete"):
        try:
            client.delete_collection(name=name)
        except NotFoundError:
            return


def count_question_chunks(bank_id: str, doc_id: str) -> list[dict]:
    """返回文档中所有题目 chunk 的元信息，供原题数量统计。

    返回 [{section, text}]；空列表表示材料没有题号结构（无法统计）。
    """
    col = get_collection(bank_id, create=False)
    if col is None:
        return []
    with _operation("read"):
        data = col.get(where={"doc_id": doc_id}, include=["metadatas", "documents"])
        metadata, documents = data["metadatas"], data["documents"]
        if metadata is None or documents is None:
            raise ValueError("missing document fields")
        out: list[dict] = []
        for meta, doc_text in zip(metadata, documents, strict=True):
            if meta.get("chunk_type") == "question":
                out.append({"section": meta.get("section", ""), "text": doc_text})
        return out

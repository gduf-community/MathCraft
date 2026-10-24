"""Ollama 向量化封装（langchain-ollama）。惰性初始化，连接失败给明确提示。"""
from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from riddleme.config import settings


class EmbeddingUnavailable(RuntimeError):
    pass


@lru_cache
def get_embeddings() -> OllamaEmbeddings:
    try:
        emb = OllamaEmbeddings(
            model=settings.embed_model,
            dimensions=settings.embed_dim,
            base_url=settings.ollama_base_url,
        )
        # 立即探测一次，失败尽早暴露
        emb.embed_query("连通性测试")
        return emb
    except Exception as exc:  # 连接拒绝、模型未拉取等
        raise EmbeddingUnavailable(
            f"无法连接 Ollama（{settings.ollama_base_url}，模型 {settings.embed_model}）。"
            f"请确认 ollama serve 已启动且模型已拉取。原始错误：{exc}"
        ) from exc


def embed_one(text: str) -> list[float]:
    return get_embeddings().embed_query(text)


def embed_many(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    # Ollama 单批过大可能超时，按 32 条分批
    out: list[list[float]] = []
    for i in range(0, len(texts), 32):
        out.extend(get_embeddings().embed_documents(texts[i : i + 32]))
    return out

"""硅基流动重排序：BAAI/bge-reranker-v2-m3，/v1/rerank。密钥写死于 local_secrets。"""
import httpx

from app import local_secrets
from app.config import settings

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


class RerankError(RuntimeError):
    pass


def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
    """返回按相关性降序的 [{"index": 原始下标, "score": 相关性}]。失败抛 RerankError，由调用方降级。"""
    if not documents:
        return []
    try:
        resp = httpx.post(
            f"{settings.siliconflow_base_url}/rerank",
            headers={"Authorization": f"Bearer {local_secrets.SILICONFLOW_API_KEY}"},
            json={"model": RERANK_MODEL, "query": query, "documents": documents, "top_n": top_n or len(documents)},
            timeout=60.0,
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        return [{"index": r["index"], "score": float(r["relevance_score"])} for r in results]
    except Exception as exc:
        raise RerankError(f"重排序接口调用失败：{exc}") from exc

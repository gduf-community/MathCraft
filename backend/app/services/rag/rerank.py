"""平台配置的文本重排服务，未覆盖时沿用既有部署凭据。"""
import math

import httpx

from app import local_secrets
from app.services.rag_runtime import current_snapshot

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


class RerankError(RuntimeError):
    pass


def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
    """返回按相关性降序的 [{"index": 原始下标, "score": 相关性}]。失败抛 RerankError，由调用方降级。"""
    if not documents:
        return []
    config = current_snapshot().config
    try:
        resp = httpx.post(
            f"{config.rerank_base_url}/rerank",
            headers={"Authorization": f"Bearer {config.rerank_api_key or local_secrets.SILICONFLOW_API_KEY}"},
            json={"model": config.rerank_model, "query": query, "documents": documents, "top_n": top_n or len(documents)},
            timeout=60.0,
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        if not isinstance(results, list) or not results:
            raise ValueError("重排结果为空或类型错误")
        seen: set[int] = set()
        ranked: list[dict] = []
        for result in results:
            index = result["index"]
            score = float(result["relevance_score"])
            if (type(index) is not int or not 0 <= index < len(documents)
                    or index in seen or not math.isfinite(score)):
                raise ValueError("重排索引或分数无效")
            seen.add(index)
            ranked.append({"index": index, "score": score})
        return ranked
    except (httpx.HTTPError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RerankError("重排服务请求失败，请检查模型、地址、凭据及响应格式") from exc

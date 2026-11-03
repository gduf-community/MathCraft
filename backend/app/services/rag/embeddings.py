"""硅基流动向量嵌入：BAAI/bge-m3，OpenAI 兼容 /v1/embeddings。密钥写死于 local_secrets。"""
import httpx

from app import local_secrets
from app.config import settings

EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIM = 1024
_BATCH = 32


class EmbeddingError(RuntimeError):
    pass


def _headers() -> dict:
    if not local_secrets.SILICONFLOW_API_KEY:
        raise EmbeddingError("SILICONFLOW_API_KEY 未配置（app/local_secrets.py）")
    return {"Authorization": f"Bearer {local_secrets.SILICONFLOW_API_KEY}"}


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    out: list[list[float]] = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(texts), _BATCH):
            try:
                resp = client.post(
                    f"{settings.siliconflow_base_url}/embeddings",
                    headers=_headers(),
                    json={"model": EMBED_MODEL, "input": texts[i : i + _BATCH]},
                )
                resp.raise_for_status()
                data = sorted(resp.json()["data"], key=lambda d: d["index"])
                out.extend(d["embedding"] for d in data)
            except Exception as exc:
                raise EmbeddingError(f"硅基流动向量接口调用失败：{exc}") from exc
    return out


def embed_one(text: str) -> list[float]:
    return embed_texts([text])[0]

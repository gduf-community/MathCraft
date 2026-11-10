"""OpenAI 兼容向量服务；平台配置优先，未覆盖时沿用既有部署凭据。"""
import logging
import math
from typing import Literal

import httpx

from app import local_secrets
from app.services.rag_runtime import current_snapshot

EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIM = 1024
_BATCH = 32
logger = logging.getLogger(__name__)
ErrorCategory = Literal[
    "authentication", "rate_limit", "timeout", "connection", "server", "request", "invalid_response",
]
_MESSAGES: dict[ErrorCategory, str] = {
    "authentication": "向量服务鉴权失败，请联系管理员检查凭据与权限",
    "rate_limit": "向量服务限流，请稍后重新解析",
    "timeout": "向量服务请求超时，请稍后重试",
    "connection": "无法连接向量服务，请联系管理员检查连接配置",
    "server": "向量服务端暂不可用，请稍后重试",
    "request": "向量服务请求失败，请联系管理员检查模型与服务配置",
    "invalid_response": "向量服务返回无效响应，请联系管理员检查模型与响应格式",
}


class EmbeddingError(RuntimeError):
    """向量服务错误；消息可直接向用户展示，分类供边界调用方使用。"""

    def __init__(self, message: str, category: ErrorCategory = "request",
                 status_code: int | None = None):
        self.category = category
        self.status_code = status_code
        super().__init__(message)


def _failure(category: ErrorCategory, exc: Exception) -> EmbeddingError:
    """只记录类别、异常类型与 HTTP 状态，禁止输出地址、正文及请求头。"""
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    logger.warning("Embedding failure category=%s type=%s status=%s",
                   category, type(exc).__name__, status)
    return EmbeddingError(_MESSAGES[category], category, status)


def default_key_configured() -> bool:
    """仅公开现有部署凭据是否存在，不暴露其内容。"""
    return bool(local_secrets.SILICONFLOW_API_KEY)


def _headers(api_key: str | None = None) -> dict[str, str]:
    key = api_key or local_secrets.SILICONFLOW_API_KEY
    if not key:
        logger.warning("Embedding failure category=authentication type=MissingCredentials status=None")
        raise EmbeddingError("系统向量服务凭据尚未配置，请联系管理员", "authentication")
    return {"Authorization": f"Bearer {key}"}


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量生成有限数值向量，验证数量、顺序与维度一致性。"""
    if not texts:
        return []
    config = current_snapshot().config
    out: list[list[float]] = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(texts), _BATCH):
            try:
                resp = client.post(
                    f"{config.embedding_base_url}/embeddings",
                    headers=_headers(config.embedding_api_key),
                    json={"model": config.embedding_model, "input": texts[i : i + _BATCH]},
                )
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ValueError("invalid response structure")
                data = payload["data"]
                if any(not isinstance(item, dict) or type(item.get("index")) is not int
                       for item in data):
                    raise ValueError("invalid response index")
                data = sorted(data, key=lambda d: d["index"])
                if [d["index"] for d in data] != list(range(len(texts[i:i + _BATCH]))):
                    raise ValueError("向量响应数量或顺序错误")
                for item in data:
                    if not isinstance(item.get("embedding"), list) or any(
                        type(value) not in (int, float) for value in item["embedding"]
                    ):
                        raise ValueError("invalid response vector")
                    vector = [float(value) for value in item["embedding"]]
                    if (not vector or not all(math.isfinite(value) for value in vector)
                            or (out and len(vector) != len(out[0]))):
                        raise ValueError("向量响应维度或数值错误")
                    out.append(vector)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                category: ErrorCategory
                if status in (401, 403):
                    category = "authentication"
                elif status == 429:
                    category = "rate_limit"
                elif status in (408, 504):
                    category = "timeout"
                elif status >= 500:
                    category = "server"
                else:
                    category = "request"
                raise _failure(category, exc) from exc
            except httpx.TimeoutException as exc:
                raise _failure("timeout", exc) from exc
            except httpx.RequestError as exc:
                raise _failure("connection", exc) from exc
            except httpx.HTTPError as exc:
                raise _failure("request", exc) from exc
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise _failure("invalid_response", exc) from exc
    return out


def embed_one(text: str) -> list[float]:
    """生成一个文本向量。"""
    return embed_texts([text])[0]

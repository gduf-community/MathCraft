"""HyDE 查询优化：先用 DeepSeek 按知识点生成假设教材段落，再用于稠密检索。

规则（v2 文档 6.4）：
- 仅在有 scope 且配置了 DeepSeek 密钥时启用
- 结果按 bank+document+scope+difficulty 哈希缓存到 Redis（TTL 1 小时）
- 生成失败返回 None，降级为原始查询，不阻断出题
"""
import hashlib
from collections.abc import Callable

import redis

from app.services import cache
from app.services.generation_cancellation import GenerationCanceled, cancellation_kwargs
from app.services.rag import llm
from app.services.rag.prompts import HYDE_SYSTEM, HYDE_USER_TEMPLATE

_HYDE_TTL = 3600


def _digest(bank_id: str, document_id: str, scope: str, difficulty: str) -> str:
    raw = f"{bank_id}|{document_id}|{scope}|{difficulty}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def generate_hyde(
    scope: str, api_key: str | None, cancel_check: Callable[[], None] | None = None,
) -> str | None:
    """生成假设段落；普通失败降级，取消异常交回调用方。"""
    try:
        text = llm.chat_text(
            [
                {"role": "system", "content": HYDE_SYSTEM},
                {"role": "user", "content": HYDE_USER_TEMPLATE.format(scope=scope)},
            ],
            api_key=api_key,
            temperature=0.3,
            max_tokens=600,
            thinking_off=True,
            **cancellation_kwargs(cancel_check),
        )
        return text.strip() or None
    except GenerationCanceled:
        raise
    except Exception:
        return None


def get_hyde(
    r: redis.Redis,
    bank_id: str,
    document_id: str,
    scope: str,
    difficulty: str,
    api_key: str | None,
) -> str | None:
    scope = (scope or "").strip()
    if not scope or not api_key:
        return None
    key = cache.PREFIX_HYDE.format(digest=_digest(bank_id, document_id, scope, difficulty))
    cached = r.get(key)
    if cached:
        return cached.decode("utf-8") if isinstance(cached, bytes) else cached
    text = generate_hyde(scope, api_key)
    if text:
        r.set(key, text, ex=_HYDE_TTL)
    return text

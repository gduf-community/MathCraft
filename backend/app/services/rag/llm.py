"""DeepSeek 客户端（OpenAI 兼容协议）。

凭据解析优先级：个人 API Key（用户设置）→ 平台级加密凭据（管理员配置，
Fernet 加密存库）→ 部署环境变量。前两者均可覆盖模型与接口地址。
"""
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

from httpx import TimeoutException
from openai import APIStatusError, APITimeoutError, OpenAI

from app.config import settings
from app.services.generation_cancellation import (
    GenerationCanceled,
    check_cancellation,
    run_checked,
)
from app.services.phoenix_tracing import MetadataClient


class LLMError(RuntimeError):
    """模型调用失败；只有白名单中的固定提示可直接公开。"""


_MISSING_KEY = "DeepSeek API Key 未配置：请到设置 → 模型与服务中填写"
_INVALID_JSON = "模型返回的 JSON 无法解析，请重试"
_GENERIC_ERROR = "模型调用失败，请稍后重试"
_BALANCE_ERROR = "DeepSeek 账户余额不足，请到设置 → 模型与服务更换密钥或充值后重试"
_AUTH_ERROR = "DeepSeek API Key 无效，请到设置 → 模型与服务检查密钥"
_RATE_ERROR = "模型接口请求过于频繁，请等一两分钟再试"
_TIMEOUT_ERROR = "模型响应超时，请稍后重试"
_STATUS_ERRORS = {401: _AUTH_ERROR, 402: _BALANCE_ERROR, 429: _RATE_ERROR}
_SAFE_ERRORS = frozenset({
    _MISSING_KEY, _INVALID_JSON, _GENERIC_ERROR, _BALANCE_ERROR,
    _AUTH_ERROR, _RATE_ERROR, _TIMEOUT_ERROR,
})


# 关闭思考模式：出题、评分、解析都只需要结论，开着思考时推理会吃满输出预算，
# 单道题能从十秒拖到三分钟以上，多题并发直接撞超时。
THINKING_OFF = {"thinking": {"type": "disabled"}}
# 开启思考模式：解题链路专用，先推理后作答提升答案可靠性
THINKING_ON = {"thinking": {"type": "enabled"}}


def friendly_error(exc: Exception) -> str:
    """仅返回固定提示，LLMError 的任意文本同样视为不可信。"""
    text = str(exc)
    if isinstance(exc, LLMError) and text in _SAFE_ERRORS:
        return text
    if isinstance(exc, (APITimeoutError, TimeoutException, TimeoutError)):
        return _TIMEOUT_ERROR
    if isinstance(exc, APIStatusError) and exc.status_code in _STATUS_ERRORS:
        return _STATUS_ERRORS[exc.status_code]
    lower = text.lower()
    if "insufficient balance" in lower or "402" in text:
        return _BALANCE_ERROR
    if "invalid_api_key" in text or "401" in text:
        return _AUTH_ERROR
    if "429" in text or "rate limit" in lower or "频率" in text:
        return _RATE_ERROR
    if "timeout" in lower or "timed out" in lower:
        return _TIMEOUT_ERROR
    return _GENERIC_ERROR


_clients: dict[tuple[str, str, str], OpenAI] = {}
_platform_cache: tuple[str, str, str] | None = None
_platform_cached_at = 0.0
_PLATFORM_TTL_SECONDS = 30
_platform_lock = Lock()
_platform_generation = 0


@dataclass(frozen=True)
class LlmRuntime:
    """一次调用的完整内存凭据快照；来源决定是否允许个人密钥回退。"""

    api_key: str = field(repr=False)
    base_url: str
    model: str
    source: Literal["personal", "platform", "deployment"]

    @property
    def credentials(self) -> tuple[str, str, str]:
        """供客户端缓存使用的完整三元组。"""
        return self.api_key, self.base_url, self.model


class ResolvedApiKey(str):
    """兼容旧 key 参数的内存快照；保留 str 比较与判空行为。"""

    runtime: LlmRuntime

    def __new__(cls, runtime: LlmRuntime):
        instance = super().__new__(cls, runtime.api_key)
        instance.runtime = runtime
        return instance

    def __repr__(self) -> str:
        return f"ResolvedApiKey(source={self.runtime.source!r})"


def invalidate_platform_cache() -> None:
    """管理员保存模型配置后立即使平台凭据缓存失效。"""
    global _platform_cache, _platform_cached_at, _platform_generation
    with _platform_lock:
        _platform_generation += 1
        _platform_cache = None
        _platform_cached_at = 0.0


def get_platform_llm() -> tuple[str, str, str] | None:
    """读取平台级模型凭据（加密存储，管理员配置）；未配置或解密失败返回 None。"""
    global _platform_cache, _platform_cached_at
    with _platform_lock:
        now = time.monotonic()
        if _platform_cached_at and now - _platform_cached_at < _PLATFORM_TTL_SECONDS:
            return _platform_cache
        generation = _platform_generation
    try:
        from app.db import SessionLocal
        from app.models.platform_llm import PlatformLlmSetting
        from app.services.secure_store import decrypt_secret

        with SessionLocal() as db:
            row = db.get(PlatformLlmSetting, 1)
            key = decrypt_secret(row.encrypted_key) if row else None
            value = (
                key,
                row.base_url or settings.deepseek_base_url,
                row.model or settings.deepseek_model,
            ) if row and key else None
    except GenerationCanceled:
        raise
    except Exception:  # noqa: BLE001  凭据读取失败回退部署环境变量
        value = None
    with _platform_lock:
        if generation == _platform_generation:
            _platform_cache = value
            _platform_cached_at = time.monotonic()
    return value


def resolve_llm_runtime(api_key: str | None = None) -> LlmRuntime:
    """一次解析来源、密钥、地址与模型，已解析的旧接口参数不再读取平台。"""
    if isinstance(api_key, ResolvedApiKey):
        return api_key.runtime
    platform = get_platform_llm()
    if api_key:
        return LlmRuntime(
            api_key, platform[1] if platform else settings.deepseek_base_url,
            platform[2] if platform else settings.deepseek_model, "personal",
        )
    if platform:
        return LlmRuntime(*platform, source="platform")
    return LlmRuntime(
        settings.deepseek_api_key, settings.deepseek_base_url,
        settings.deepseek_model, "deployment",
    )


def resolve_runtime(api_key: str | None = None) -> tuple[str, str, str]:
    """解析本次调用的凭据，返回 (api_key, base_url, model)。"""
    return resolve_llm_runtime(api_key).credentials


def get_client(
    api_key: str | None = None, *, runtime: LlmRuntime | tuple[str, str, str] | None = None,
) -> OpenAI:
    """按完整运行凭据缓存客户端，兼容既有 api_key 调用。"""
    if isinstance(runtime, LlmRuntime):
        runtime = runtime.credentials
    api_key, base_url, model = runtime if runtime is not None else resolve_runtime(api_key)
    if not api_key:
        raise LLMError(_MISSING_KEY)
    cache_key = (api_key, base_url, model)
    cli = _clients.get(cache_key)
    if cli is None:
        cli = OpenAI(api_key=api_key, base_url=base_url,
                     timeout=float(settings.llm_timeout_seconds), max_retries=0,
                     http_client=MetadataClient(model))
        _clients[cache_key] = cli
    return cli


def _create(
    kwargs: dict, runtime: LlmRuntime, thinking_off: bool,
    cancel_check: Callable[[], None] | None = None, *, thinking: bool | None = None,
):
    """检查每次实际请求；显式 thinking 优先于旧版 thinking_off。"""
    check_cancellation(cancel_check)
    client = get_client(runtime=runtime)
    extra = THINKING_ON if thinking is True else (
        THINKING_OFF if thinking is False or thinking_off else None
    )
    if extra is not None:
        try:
            check_cancellation(cancel_check)
            return client.chat.completions.create(**kwargs, extra_body=extra)
        except GenerationCanceled:
            raise
        except Exception as exc:  # noqa: BLE001
            if (not isinstance(exc, APIStatusError) or exc.status_code not in (400, 422)
                    or "thinking" not in str(exc).lower()):
                raise
    check_cancellation(cancel_check)
    return client.chat.completions.create(**kwargs)


def _platform_retry(runtime: LlmRuntime, exc: Exception) -> LlmRuntime | None:
    """个人凭据的 401/403 只允许回退到不同的平台凭据一次。"""
    if (runtime.source != "personal" or not isinstance(exc, APIStatusError)
            or exc.status_code not in (401, 403)):
        return None
    platform = get_platform_llm()
    return LlmRuntime(*platform, source="platform") if (
        platform and platform[0] != runtime.api_key
    ) else None


def _request(
    kwargs: dict, runtime: LlmRuntime, api_key: str | None,
    thinking_off: bool, cancel_check: Callable[[], None] | None,
    *, thinking: bool | None,
):
    """保留请求参数与解析预算，仅在个人鉴权失败时切换完整平台三元组。"""
    try:
        response = _create(kwargs, runtime, thinking_off, cancel_check, thinking=thinking)
    except GenerationCanceled:
        raise
    except Exception as exc:  # noqa: BLE001
        check_cancellation(cancel_check)
        fallback = _platform_retry(runtime, exc)
        if fallback is None:
            raise
        check_cancellation(cancel_check)
        response = _create(
            {**kwargs, "model": fallback.model}, fallback, thinking_off, cancel_check,
            thinking=thinking,
        )
        runtime = fallback
    return response, runtime


def chat_json(
    messages: list[dict],
    api_key: str | None = None,
    retries: int = 1,
    max_tokens: int | None = None,
    thinking_off: bool = False,
    cancel_check: Callable[[], None] | None = None,
    *, thinking: bool | None = None, temperature: float = 0.7,
) -> dict:
    """请求 JSON；仅解析错误重试，保留取消参数位置与思考模式关键字约定。"""
    msgs = list(messages)
    budget = max_tokens
    left = retries
    escalations = 0
    try:
        runtime = run_checked(cancel_check, resolve_llm_runtime, api_key)
        while True:
            check_cancellation(cancel_check)
            kwargs: dict = {
                "model": runtime.model, "messages": msgs,
                "response_format": {"type": "json_object"}, "temperature": temperature,
            }
            if budget:
                kwargs["max_tokens"] = budget
            resp, runtime = run_checked(
                cancel_check, _request, kwargs, runtime, api_key, thinking_off, cancel_check,
                thinking=thinking,
            )
            content = resp.choices[0].message.content or ""
            try:
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise json.JSONDecodeError("顶层必须是 JSON 对象", content, 0)
                return data
            except json.JSONDecodeError as exc:
                check_cancellation(cancel_check)
                temperature = 0.3
                if budget and escalations < 2:
                    escalations += 1
                    budget = int(budget * 1.6)
                    continue
                if left > 0:
                    left -= 1
                    msgs = msgs + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": (
                            f"上面的输出无法解析为 JSON（错误：{exc}）。请严格只输出合法 JSON。"
                        )},
                    ]
                    continue
                raise LLMError(_INVALID_JSON) from None
    except GenerationCanceled:
        raise
    except Exception as exc:  # noqa: BLE001
        check_cancellation(cancel_check)
        raise LLMError(friendly_error(exc)) from None


def chat_text(
    messages: list[dict],
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    thinking_off: bool = False,
    response_format: dict | None = None,
    cancel_check: Callable[[], None] | None = None,
    *, thinking: bool | None = None,
) -> str:
    """返回文本，保持参数、取消传播与固定安全错误。"""
    try:
        runtime = run_checked(cancel_check, resolve_llm_runtime, api_key)
        kwargs: dict = {"model": runtime.model, "messages": messages, "temperature": temperature}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if response_format:
            kwargs["response_format"] = response_format
        resp, _ = run_checked(
            cancel_check, _request, kwargs, runtime, api_key, thinking_off, cancel_check,
            thinking=thinking,
        )
        return resp.choices[0].message.content or ""
    except GenerationCanceled:
        raise
    except Exception as exc:  # noqa: BLE001
        check_cancellation(cancel_check)
        raise LLMError(friendly_error(exc)) from None


def chat_stream(
    messages: list[dict],
    api_key: str | None = None,
    max_tokens: int | None = None,
    thinking_off: bool = False,
    temperature: float = 0.7,
    cancel_check: Callable[[], None] | None = None,
    *, thinking: bool | None = None,
) -> Iterator[str]:
    """流式交付增量；等待已发起的流退出并关闭后再传播取消。"""
    try:
        runtime = run_checked(cancel_check, resolve_llm_runtime, api_key)
        kwargs: dict = {
            "model": runtime.model, "messages": messages, "temperature": temperature, "stream": True,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp, _ = _request(
            kwargs, runtime, api_key, thinking_off, cancel_check, thinking=thinking,
        )
        try:
            for chunk in resp:
                choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
                delta = getattr(choice, "delta", None) if choice else None
                piece = getattr(delta, "content", None) if delta else None
                if piece:
                    yield piece
        finally:
            resp.close()
        check_cancellation(cancel_check)
    except GenerationCanceled:
        raise
    except Exception as exc:  # noqa: BLE001
        check_cancellation(cancel_check)
        raise LLMError(friendly_error(exc)) from None

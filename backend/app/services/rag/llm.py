"""DeepSeek 客户端（OpenAI 兼容协议）。

凭据解析优先级：个人 API Key（用户设置）→ 平台级加密凭据（管理员配置，
Fernet 加密存库）→ 部署环境变量。前两者均可覆盖模型与接口地址。
"""
import json
import time
from collections.abc import Iterator

from httpx import TimeoutException
from openai import APIStatusError, APITimeoutError, OpenAI

from app.config import settings
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


def get_platform_llm() -> tuple[str, str, str] | None:
    """读取平台级模型凭据（加密存储，管理员配置）；未配置或解密失败返回 None。"""
    global _platform_cache, _platform_cached_at
    now = time.monotonic()
    if _platform_cached_at and now - _platform_cached_at < _PLATFORM_TTL_SECONDS:
        return _platform_cache
    try:
        from app.db import SessionLocal
        from app.models.platform_llm import PlatformLlmSetting
        from app.services.secure_store import decrypt_secret

        db = SessionLocal()
        try:
            row = db.get(PlatformLlmSetting, 1)
            key = decrypt_secret(row.encrypted_key) if row else None
        finally:
            db.close()
        if row and key:
            _platform_cache = (
                key,
                row.base_url or settings.deepseek_base_url,
                row.model or settings.deepseek_model,
            )
        else:
            _platform_cache = None
        _platform_cached_at = now
        return _platform_cache
    except Exception:  # noqa: BLE001  凭据读取失败回退部署环境变量
        _platform_cache = None
        _platform_cached_at = now
        return None


def resolve_runtime(api_key: str | None = None) -> tuple[str, str, str]:
    """解析本次调用的凭据，返回 (api_key, base_url, model)。"""
    platform = get_platform_llm()
    if api_key:
        base_url = (platform[1] if platform else "") or settings.deepseek_base_url
        model = (platform[2] if platform else "") or settings.deepseek_model
        return api_key, base_url, model
    if platform:
        return platform
    return settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model


def get_client(runtime: tuple[str, str, str]) -> OpenAI:
    api_key, base_url, model = runtime
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


def _create(kwargs: dict, runtime: tuple[str, str, str], thinking_off: bool,
            thinking: bool | None = None):
    """统一调用入口：thinking 显式三态（True=开启 / False=关闭 / None=服务端默认），
    接口不认这个字段时退回默认调用。"""
    client = get_client(runtime)
    if thinking is True:
        try:
            return client.chat.completions.create(**kwargs, extra_body=THINKING_ON)
        except Exception as exc:  # noqa: BLE001
            if "thinking" not in str(exc).lower():
                raise
    if thinking_off:
        try:
            return client.chat.completions.create(**kwargs, extra_body=THINKING_OFF)
        except Exception as exc:  # noqa: BLE001
            if "thinking" not in str(exc).lower():
                raise
    return client.chat.completions.create(**kwargs)


def _platform_retry(api_key: str | None, exc: Exception) -> tuple[str, str, str] | None:
    """个人 Key 请求遭遇 401/403 时，若平台凭据可用且不同，返回平台 runtime 以便重试。

    个人设置里保存的旧 Key 失效是最常见的凭据故障：不回退会让意图识别、
    出题、答疑全部静默降级。平台 Key 自身 401 时不重试，避免双倍等待。
    """
    if not isinstance(exc, APIStatusError) or exc.status_code not in (401, 403):
        return None
    if not api_key:
        return None
    platform = get_platform_llm()
    if platform and platform[0] != api_key:
        return platform
    return None


def chat_json(
    messages: list[dict],
    api_key: str | None = None,
    retries: int = 1,
    max_tokens: int | None = None,
    thinking_off: bool = False,
    thinking: bool | None = None,
) -> dict:
    """调用模型并要求 JSON 输出。

    只有「输出不是合法 JSON」才重试；超时、连接失败等传输错误直接抛出，
    否则一次超时会被重试放大成两倍等待。输出被截断时先放大预算重来，
    回喂半截 JSON 没有意义；预算放大两次仍不行才回喂错误再试。
    thinking=True 显式开启思考模式（解题链路用），优先级高于 thinking_off。
    """
    msgs = list(messages)
    budget = max_tokens
    left = retries
    escalations = 0
    temperature = 0.7
    runtime = resolve_runtime(api_key)
    while True:
        try:
            kwargs: dict = {
                "model": runtime[2],
                "messages": msgs,
                "response_format": {"type": "json_object"},
                "temperature": temperature,
            }
            if budget:
                kwargs["max_tokens"] = budget
            resp = _create(kwargs, runtime, thinking_off, thinking)
            choice = resp.choices[0]
            return json.loads(choice.message.content or "")
        except json.JSONDecodeError as exc:
            content = choice.message.content or ""
            temperature = 0.3
            if budget and escalations < 2:
                escalations += 1
                budget = int(budget * 1.6)
                continue
            if left > 0:
                left -= 1
                msgs = msgs + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"上面的输出无法解析为 JSON（错误：{exc}）。请严格只输出合法 JSON。"},
                ]
                continue
            raise LLMError(_INVALID_JSON) from None
        except Exception as exc:  # noqa: BLE001
            retry_runtime = _platform_retry(api_key, exc)
            if retry_runtime:
                return chat_json(messages, api_key=retry_runtime[0], retries=retries,
                                 max_tokens=max_tokens, thinking_off=thinking_off,
                                 thinking=thinking)
            raise LLMError(friendly_error(exc)) from None


def chat_text(
    messages: list[dict],
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    thinking_off: bool = False,
    response_format: dict | None = None,
) -> str:
    """返回模型文本，调用与响应异常仅以固定安全提示抛出。"""
    runtime = resolve_runtime(api_key)
    kwargs: dict = {"model": runtime[2], "messages": messages, "temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if response_format:
        kwargs["response_format"] = response_format
    try:
        resp = _create(kwargs, runtime, thinking_off)
        return resp.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001
        retry_runtime = _platform_retry(api_key, exc)
        if retry_runtime:
            return chat_text(messages, api_key=retry_runtime[0], temperature=temperature,
                             max_tokens=max_tokens, thinking_off=thinking_off,
                             response_format=response_format)
        raise LLMError(friendly_error(exc)) from None


def chat_stream(
    messages: list[dict],
    api_key: str | None = None,
    max_tokens: int | None = None,
    thinking_off: bool = False,
    temperature: float = 0.7,
) -> Iterator[str]:
    """流式返回增量文本；参数与 _create 一致，供出题链路边生成边校验。"""
    runtime = resolve_runtime(api_key)
    kwargs: dict = {
        "model": runtime[2], "messages": messages,
        "temperature": temperature, "stream": True,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    try:
        resp = _create(kwargs, runtime, thinking_off)
        try:
            for chunk in resp:
                choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
                delta = getattr(choice, "delta", None) if choice else None
                piece = getattr(delta, "content", None) if delta else None
                if piece:
                    yield piece
        finally:
            resp.close()
    except Exception as exc:  # noqa: BLE001
        retry_runtime = _platform_retry(api_key, exc)
        if retry_runtime:
            yield from chat_stream(messages, api_key=retry_runtime[0],
                                   max_tokens=max_tokens, thinking_off=thinking_off,
                                   temperature=temperature)
            return
        raise LLMError(friendly_error(exc)) from None

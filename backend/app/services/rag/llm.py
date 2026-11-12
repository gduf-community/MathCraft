"""DeepSeek 客户端（OpenAI 兼容协议）。密钥按用户传入，未传时回退环境变量。"""
import json

from openai import OpenAI

from app.config import settings


class LLMError(RuntimeError):
    pass


# 关闭思考模式：出题、评分、解析都只需要结论，开着思考时推理会吃满输出预算，
# 单道题能从十秒拖到三分钟以上，多题并发直接撞超时。
THINKING_OFF = {"thinking": {"type": "disabled"}}


def friendly_error(exc: Exception) -> str:
    """把模型接口错误翻译成用户能看懂的一句话。"""
    text = str(exc)
    lower = text.lower()
    if "Insufficient Balance" in text or "402" in text:
        return "DeepSeek 账户余额不足，请到设置 → 模型与服务更换密钥或充值后重试"
    if "invalid_api_key" in text or "401" in text:
        return "DeepSeek API Key 无效，请到设置 → 模型与服务检查密钥"
    if "429" in text or "rate limit" in lower or "频率" in text:
        return "模型接口请求过于频繁，请等一两分钟再试"
    if "timeout" in lower or "timed out" in lower:
        return "模型响应超时，请稍后重试"
    return f"模型调用失败：{exc}"


_clients: dict[str, OpenAI] = {}


def get_client(api_key: str | None = None) -> OpenAI:
    key = api_key or settings.deepseek_api_key
    if not key:
        raise LLMError("DeepSeek API Key 未配置：请到设置 → 模型与服务中填写")
    cli = _clients.get(key)
    if cli is None:
        cli = OpenAI(api_key=key, base_url=settings.deepseek_base_url,
                     timeout=float(settings.llm_timeout_seconds), max_retries=0)
        _clients[key] = cli
    return cli


def _create(kwargs: dict, api_key: str | None, thinking_off: bool):
    """统一调用入口：按需关闭思考模式，接口不认这个字段时退回默认调用。"""
    client = get_client(api_key)
    if thinking_off:
        try:
            return client.chat.completions.create(**kwargs, extra_body=THINKING_OFF)
        except Exception as exc:  # noqa: BLE001
            if "thinking" not in str(exc).lower():
                raise
    return client.chat.completions.create(**kwargs)


def chat_json(
    messages: list[dict],
    api_key: str | None = None,
    retries: int = 1,
    max_tokens: int | None = None,
    thinking_off: bool = False,
) -> dict:
    """调用模型并要求 JSON 输出。

    只有「输出不是合法 JSON」才重试；超时、连接失败等传输错误直接抛出，
    否则一次超时会被重试放大成两倍等待。输出被截断时先放大预算重来，
    回喂半截 JSON 没有意义；预算放大两次仍不行才回喂错误再试。
    """
    last_err: Exception | None = None
    msgs = list(messages)
    budget = max_tokens
    left = retries
    escalations = 0
    temperature = 0.7
    while True:
        try:
            kwargs: dict = {
                "model": settings.deepseek_model,
                "messages": msgs,
                "response_format": {"type": "json_object"},
                "temperature": temperature,
            }
            if budget:
                kwargs["max_tokens"] = budget
            resp = _create(kwargs, api_key, thinking_off)
            choice = resp.choices[0]
            return json.loads(choice.message.content or "")
        except json.JSONDecodeError as exc:
            last_err = exc
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
            raise LLMError(f"模型返回的 JSON 无法解析：{last_err}") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(friendly_error(exc)) from exc


def chat_text(
    messages: list[dict],
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    thinking_off: bool = False,
    response_format: dict | None = None,
) -> str:
    kwargs: dict = {"model": settings.deepseek_model, "messages": messages, "temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if response_format:
        kwargs["response_format"] = response_format
    resp = _create(kwargs, api_key, thinking_off)
    return resp.choices[0].message.content or ""


def chat_stream(
    messages: list[dict],
    api_key: str | None = None,
    max_tokens: int | None = None,
    thinking_off: bool = False,
    temperature: float = 0.7,
):
    """流式返回增量文本；参数与 _create 一致，供出题链路边生成边校验。"""
    kwargs: dict = {
        "model": settings.deepseek_model, "messages": messages,
        "temperature": temperature, "stream": True,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    resp = _create(kwargs, api_key, thinking_off)
    for chunk in resp:
        choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
        delta = getattr(choice, "delta", None) if choice else None
        piece = getattr(delta, "content", None) if delta else None
        if piece:
            yield piece

"""DeepSeek 客户端（OpenAI 兼容协议）。密钥按用户传入，未传时回退环境变量。"""
import json

from openai import OpenAI

from app.config import settings


class LLMError(RuntimeError):
    pass


_clients: dict[str, OpenAI] = {}


def get_client(api_key: str | None = None) -> OpenAI:
    key = api_key or settings.deepseek_api_key
    if not key:
        raise LLMError("DeepSeek API Key 未配置：请到个人中心 → 模型配置中填写")
    cli = _clients.get(key)
    if cli is None:
        cli = OpenAI(api_key=key, base_url=settings.deepseek_base_url, timeout=120.0)
        _clients[key] = cli
    return cli


def chat_json(messages: list[dict], api_key: str | None = None, retries: int = 1) -> dict:
    """调用模型并要求 JSON 输出。解析失败把错误回喂重试。"""
    last_err: Exception | None = None
    msgs = list(messages)
    content = ""
    for attempt in range(retries + 1):
        try:
            resp = get_client(api_key).chat.completions.create(
                model=settings.deepseek_model,
                messages=msgs,
                response_format={"type": "json_object"},
                temperature=0.7 if attempt == 0 else 0.3,
            )
            content = resp.choices[0].message.content or ""
            return json.loads(content)
        except Exception as exc:
            last_err = exc
            if content:
                msgs = msgs + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"上面的输出无法解析为 JSON（错误：{exc}）。请严格只输出合法 JSON。"},
                ]
    raise LLMError(f"DeepSeek JSON 输出解析失败：{last_err}")


def chat_text(
    messages: list[dict],
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> str:
    kwargs: dict = {"model": settings.deepseek_model, "messages": messages, "temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    resp = get_client(api_key).chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""

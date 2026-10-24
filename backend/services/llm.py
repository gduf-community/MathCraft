"""DeepSeek 客户端封装（OpenAI 兼容协议）。"""
from functools import lru_cache

from openai import OpenAI

from config import settings


class LLMError(RuntimeError):
    pass


@lru_cache
def get_client() -> OpenAI:
    if not settings.deepseek_api_key:
        raise LLMError("DEEPSEEK_API_KEY 未配置，请在 backend/.env 中填写")
    return OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)


def chat_json(messages: list[dict], retries: int = 1) -> dict:
    """调用模型并要求 JSON 输出。返回 dict，解析失败带错误重试。"""
    import json

    last_err: Exception | None = None
    msgs = list(messages)
    content = ""
    for attempt in range(retries + 1):
        try:
            resp = get_client().chat.completions.create(
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
                # 把解析错误回喂给模型，要求修正
                msgs = msgs + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"上面的输出无法解析为 JSON（错误：{exc}）。请严格只输出合法 JSON。"},
                ]
    raise LLMError(f"DeepSeek JSON 输出解析失败：{last_err}")


def chat_text(messages: list[dict], temperature: float = 0.7) -> str:
    resp = get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""

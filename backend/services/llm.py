"""正式 LLM 配置适配器。

模型、提供方和密钥全部由 MathCraft 的 /api/settings 管理。
"""

from __future__ import annotations

from MathCraft.services.llm import complete
from MathCraft.utils.json_parser import parse_json_response


class LLMError(RuntimeError):
    pass


async def chat_json(messages: list[dict], retries: int = 1) -> dict | list:
    """使用正式 LLM 配置生成并解析 JSON。"""
    last_error: Exception | None = None
    request_messages = list(messages)
    for attempt in range(retries + 1):
        try:
            content = await complete(
                prompt="",
                messages=request_messages,
                response_format={"type": "json_object"},
                temperature=0.7 if attempt == 0 else 0.3,
            )
            data = parse_json_response(content, fallback=None)
            if isinstance(data, (dict, list)):
                return data
            raise LLMError("模型未返回合法 JSON 对象")
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                request_messages = request_messages + [
                    {"role": "assistant", "content": content if "content" in locals() else ""},
                    {"role": "user", "content": f"上面的输出无法解析为 JSON（错误：{exc}）。请严格只输出合法 JSON。"},
                ]
    raise LLMError(f"正式 LLM JSON 输出解析失败：{last_error}") from last_error


async def chat_text(messages: list[dict], temperature: float = 0.7) -> str:
    return await complete(prompt="", messages=messages, temperature=temperature)


__all__ = ["LLMError", "chat_json", "chat_text"]

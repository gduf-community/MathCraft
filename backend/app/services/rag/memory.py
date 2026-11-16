"""会话短期记忆：系统 Prompt + 最近 3-5 轮对话。

设计目标：让模型正确把握当前语境（上一轮的要求、已确定的题型数量难度、未完成的意图），
而不是把整段历史塞进上下文。结构固定为两段：

1. 系统 Prompt：声明当前模式、文档语境与记忆使用规则；
2. 记忆正文：最近 MEMORY_ROUNDS（3-5 取 4）轮完整对话原文，一轮 = 一条用户消息
   与紧随其后的助手回复。

记忆只在当前请求内生效，不持久化、不跨会话共享；持久化仍由 ChatMessage 落库承担。
"""
from collections.abc import Callable

from app.services.generation_cancellation import (
    GenerationCanceled, cancellation_kwargs, run_checked,
)
from app.services.rag.modes import DEFAULT_MODE, mode_label

# 短期记忆窗口：3-5 轮，取 4 轮（一轮 = user + assistant 两条消息）
MEMORY_ROUNDS = 4

MEMORY_SYSTEM_TEMPLATE = """你是数学学习平台的对话助手，当前处于「{mode_label}」模式，正在围绕文档「{doc_name}」与用户对话。
下面提供的是短期记忆：最近几轮对话的原文。使用规则：
1 结合记忆理解用户的最新消息；用户说「再来一批」「换成难的」「按刚才的要求」时，从记忆中推断指代内容。
2 记忆中已确认过的题型、数量、难度等要求，除非用户明确更改，否则保持不变。
3 记忆中没有的信息不要编造；记忆与最新消息冲突时，以最新消息为准。"""

MEMORY_BLOCK_TEMPLATE = """【短期记忆 · 当前语境】{mode_label}模式 · 文档：{doc_name}
【最近对话】
{turns}"""


def build_short_term_history(
    history: list[dict], rounds: int = MEMORY_ROUNDS
) -> list[dict]:
    """截取最近 rounds 轮完整对话，返回扁平化消息列表（保持时间顺序）。

    轮的定义：一条 user 消息与其后的 assistant 回复配为一轮。
    开头游离的 assistant 回复（没有对应的 user 开轮）不属于完整轮，直接丢弃；
    结尾的 user 消息若还没有 assistant 回复，也算一轮（正是本次请求要处理的消息前文）。
    """
    turns: list[list[dict]] = []
    current: list[dict] = []
    for item in history:
        role = str(item.get("role") or "")
        text = str(item.get("text") or "")
        if not text:
            continue
        if role == "user":
            if current:
                turns.append(current)
            current = [item]
        elif role == "assistant" and current:
            current.append(item)
    if current:
        turns.append(current)
    recent = turns[-rounds:] if rounds > 0 else []
    return [dict(item) for turn in recent for item in turn]


def build_memory_system(mode: str, doc_name: str) -> str:
    """短期记忆的系统 Prompt：声明模式、文档语境与记忆使用规则。"""
    return MEMORY_SYSTEM_TEMPLATE.format(
        mode_label=mode_label(mode or DEFAULT_MODE), doc_name=doc_name or "当前文档",
    )


def build_memory_block(mode: str, doc_name: str, history: list[dict]) -> str:
    """把系统说明与最近轮次拼成一个可嵌入用户侧 Prompt 的记忆文本块。

    供槽位抽取这类「消息必须合并为单个 user prompt」的调用方使用；
    支持标准 messages 数组的调用方（答疑）改用 build_memory_system + 轮次列表。
    """
    recent = build_short_term_history(history)
    turns = "\n".join(
        f"{'用户' if item.get('role') == 'user' else '助手'}：{item.get('text', '')}"
        for item in recent
    )
    return MEMORY_BLOCK_TEMPLATE.format(
        mode_label=mode_label(mode or DEFAULT_MODE), doc_name=doc_name or "当前文档",
        turns=turns or "（暂无历史对话）",
    )


# 自由对话的附加规则：非出题消息也要基于记忆具体、自然地回应
SMALLTALK_EXTRA = """
当前这条消息不是出题指令，请作为对话伙伴用简短自然的中文回应：
1 问候、追问、回忆之前的请求都要具体回应；用户问「我刚刚说了什么」时，
  用记忆概述最近几轮的请求要点（题型、数量、难度、范围）；
2 用户问「你是谁」这类身份问题时，说明自己是智能出题助手的对话助手，
  能基于教学材料批量出题、答疑、管理题目数据，回复保持简短友好；
3 记忆中没有的信息就明确说记忆里没有，不要编造；
4 不要生成题目、不要输出 JSON；如果用户的意图其实是要出题，
  温和提示补全题型、数量、难度与知识点范围即可。"""


def answer_casually(
    mode: str, doc_name: str, history: list[dict], message: str, api_key: str | None = None,
    *, cancel_check: Callable[[], None] | None = None,
) -> str:
    """非出题、非业务消息的自由对话：基于短期记忆自然回应。

    供快速出题模式分流使用——意图拿不准的消息不再机械追问槽位。
    失败时返回引导文案，不抛异常（对话回复不应打断会话）。
    """
    from app.services.rag.llm import chat_text

    system = build_memory_system(mode, doc_name) + SMALLTALK_EXTRA
    messages: list[dict] = [{"role": "system", "content": system}]
    for item in build_short_term_history(history):
        role = item.get("role")
        if role in ("user", "assistant") and item.get("text"):
            messages.append({"role": role, "content": str(item["text"])})
    messages.append({"role": "user", "content": message})
    try:
        reply = run_checked(
            cancel_check, chat_text, messages, api_key=api_key, temperature=0.6,
            max_tokens=600, thinking_off=True, **cancellation_kwargs(cancel_check),
        )
    except GenerationCanceled:
        raise
    except Exception:  # noqa: BLE001  对话回复失败降级为引导文案
        return "这条消息我没对应上出题需求。要出题的话，告诉我题型、数量、难度和知识点范围即可。"
    return reply.strip() or "我在的。要出题的话，告诉我题型、数量、难度和知识点范围即可。"

"""会话短期记忆：系统 Prompt + 最近 3-5 轮对话。

设计目标：让模型正确把握当前语境（上一轮的要求、已确定的题型数量难度、未完成的意图），
而不是把整段历史塞进上下文。结构固定为两段：

1. 系统 Prompt：声明当前模式、文档语境与记忆使用规则；
2. 记忆正文：最近 MEMORY_ROUNDS（3-5 取 4）轮完整对话原文，一轮 = 一条用户消息
   与紧随其后的助手回复。

记忆只在当前请求内生效，不持久化、不跨会话共享；持久化仍由 ChatMessage 落库承担。
"""
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

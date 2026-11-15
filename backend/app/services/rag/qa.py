"""知识答疑：RAG 检索教学材料，回答标注知识点所属章节，问什么答什么。

短期记忆：QA_SYSTEM + 记忆使用说明为系统 Prompt，携带最近 3-5 轮完整对话。
"""
from typing import Callable

from app.services.rag.llm import chat_text
from app.services.rag.memory import build_memory_system, build_short_term_history
from app.services.rag.retrieval import retrieve_for_generation
from app.services.rag.prompts import QA_SYSTEM

ProgressCB = Callable[[int, str], None]

_EMPTY_REPLY = "知识库里没有检索到与这个问题相关的内容。请确认文档已入库完成，或者换个说法再问一次。"


def _context(chunks: list[dict]) -> str:
    parts = []
    for c in chunks:
        section = c.get("section") or "未分节"
        parts.append(f"【{c.get('doc_name') or '文档'} · {section}】\n{c.get('text', '')}")
    return "\n\n".join(parts)


def answer_question(
    bank_id: str,
    document_id: str,
    message: str,
    history: list[dict],
    api_key: str | None = None,
    progress_cb: ProgressCB | None = None,
    mode: str = "qa",
    doc_name: str = "当前文档",
) -> str:
    """检索并回答；返回纯文本回复，引用以（见「文档 · 章节」）内联标注。"""

    def report(percent: int, stage: str) -> None:
        if progress_cb:
            progress_cb(percent, stage)

    report(12, "正在检索知识库")
    chunks = retrieve_for_generation(bank_id, message, document_id, hyde_text=None)
    if not chunks:
        return _EMPTY_REPLY
    report(48, "正在组织答案")
    system = QA_SYSTEM + "\n\n" + build_memory_system(mode, doc_name)
    messages: list[dict] = [{"role": "system", "content": system}]
    for h in build_short_term_history(history):
        role = h.get("role")
        if role in ("user", "assistant") and h.get("text"):
            messages.append({"role": role, "content": str(h["text"])})
    messages.append({"role": "user", "content": f"【教学材料】\n{_context(chunks[:6])}\n\n【问题】{message}"})
    reply = chat_text(messages, api_key=api_key, temperature=0.3, max_tokens=2400, thinking_off=True)
    report(90, "回答完成")
    return reply.strip() or "模型没有返回内容，请重试。"

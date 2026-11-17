"""知识答疑：RAG 检索教学材料作答；引用只能来自召回 chunk，宁可拒答不脑补。

降级策略：模型自判问题与召回材料的相关性——不相关时明确告知无法回答，
并提示材料覆盖的知识范围（coverage），引导用户就相关内容提问。
短期记忆：QA_SYSTEM + 记忆使用说明为系统 Prompt，携带最近 3-5 轮完整对话。
"""
from typing import Callable

from app.services.generation_cancellation import (
    cancellation_kwargs,
    check_cancellation,
    run_checked,
)
from app.services.rag.llm import LLMError, chat_json, friendly_error
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


def _coverage_hint(chunks: list[dict]) -> str:
    """从召回 chunk 的章节信息汇总材料覆盖范围，供拒答降级提示使用。"""
    seen: list[str] = []
    for c in chunks:
        label = f"{(c.get('doc_name') or '文档')} · {c.get('section') or '未分节'}"
        if label not in seen:
            seen.append(label)
    return "、".join(seen[:5]) + ("等" if len(seen) > 5 else "")


def answer_question(
    bank_id: str,
    document_id: str,
    message: str,
    history: list[dict],
    api_key: str | None = None,
    progress_cb: ProgressCB | None = None,
    mode: str = "qa",
    doc_name: str = "当前文档",
    cancel_check: Callable[[], None] | None = None,
) -> str:
    """检索并回答；引用只来自召回 chunk，不相关的问题明确拒答并提示可回答范围。"""

    def report(percent: int, stage: str) -> None:
        check_cancellation(cancel_check)
        if progress_cb:
            run_checked(cancel_check, progress_cb, percent, stage)

    report(12, "正在检索知识库")
    chunks = run_checked(
        cancel_check, retrieve_for_generation, bank_id, message, document_id, hyde_text=None,
    )
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
    try:
        data = run_checked(
            cancel_check, chat_json, messages, api_key=api_key, temperature=0.3,
            max_tokens=2400, thinking_off=True, **cancellation_kwargs(cancel_check),
        )
    except LLMError as exc:
        return friendly_error(exc)
    if not isinstance(data, dict):
        return "答疑服务暂时没有返回有效内容，请稍后再试。"
    answer = str(data.get("answer") or "").strip()
    coverage = str(data.get("coverage") or "").strip()
    if data.get("related") is not True or not answer:
        # 拒答降级：明确告知无法回答，并给出材料覆盖的知识范围
        scope_hint = coverage or _coverage_hint(chunks)
        return (
            f"这个问题超出了文档「{doc_name}」材料的覆盖范围，我不能凭空作答。\n"
            f"当前材料主要涵盖：{scope_hint}。\n"
            "你可以就上述范围内的知识点、公式或例题向我提问。"
        )
    report(90, "回答完成")
    return answer

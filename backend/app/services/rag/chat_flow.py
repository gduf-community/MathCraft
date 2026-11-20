"""对话出题编排：原始查询检索、生成及按题型配额审核补齐。"""
from typing import Callable

from app.models.ops_run import RunErrorCode
from app.schemas.question import Difficulty, GenerateParams, Question, QuestionType, TypeCount
from app.services.generation_cancellation import GenerationCanceled, cancellation_kwargs
from app.services.rag.llm import friendly_error
from app.services.rag.prompts import CREATIVE_SYSTEM_EXTRA
from app.services.rag.question_gen import NeedConfirmError, generate_questions
from app.services.rag.slots import (
    build_followup, build_natural_followup, build_params, extract_slots, merge_slots,
    missing_keys,
)

DONE_REPLY = "题目已生成完成，共 {n} 道，已同步到「题目预览」标签页。还需要生成其他题型吗？"
SHORTFALL_REPLY = (
    "实际生成 {actual} 道（你要求 {requested} 道，{reasons}已剔除）。"
    "需要的话回复「再补 {missing} 道」，我会换考点重新出。"
)
EMPTY_REPLY = "这轮题目都被查重或难度校验拦下了，没有可入库的题。换个知识点或降低数量再试试？"
PAUSED_REPLY = "已暂停本次生成，未写入题目预览。"

CONFIRM_REPLY = """材料中「{type_label}」的原题只有 {available} 道，不足 {requested} 道。你可以：
1. 只要原题，把数量改为 {available} 道
2. 保留 {requested} 道，不足的部分用改数据的变式题补齐
3. 改用改背景或全新题的模式
直接回复序号或说明你的选择即可。"""

ProgressCB = Callable[[int, str], None]
CancelCheck = Callable[[], bool]


class ChatCanceled(GenerationCanceled):
    """用户点了暂停：在阶段检查点抛出，阻止继续生成与落库。"""


def build_result_reply(
    actual: int, requested: int, stats=None, type_label: str | None = None,
    scope: str | None = None,
) -> str:
    """按审核后的真实结果写回复，数量对不上时说明原因。"""
    if actual <= 0:
        return EMPTY_REPLY
    if actual >= requested:
        context = "、".join(part for part in (
            f"知识点范围为「{scope}」" if scope else "",
            f"题型为{type_label}" if type_label else "",
        ) if part)
        return DONE_REPLY.format(n=actual) + (f"本次{context}。" if context else "")
    reasons = []
    if stats is not None:
        if getattr(stats, "duplicates", 0):
            reasons.append(f"重复 {stats.duplicates} 道")
        if getattr(stats, "regenerated", 0):
            reasons.append(f"重出后仍不合格 {stats.regenerated} 道")
    if not reasons:
        reasons.append("部分题目重复或难度不符")
    return SHORTFALL_REPLY.format(
        actual=actual,
        requested=requested,
        reasons="、".join(reasons) + "，",
        missing=requested - actual,
    )


def _guard(cancel_check: CancelCheck | None) -> None:
    if cancel_check and cancel_check():
        raise ChatCanceled


def handle_chat(
    bank_id: str,
    document_id: str,
    doc_name: str,
    message: str,
    history: list[dict],
    slot_state: dict,
    existing_stems: list[str] | None = None,
    api_key: str | None = None,
    hyde_text: str | None = None,
    images: list[str] | None = None,
    retrieve_fn=None,
    progress_cb: ProgressCB | None = None,
    cancel_check: CancelCheck | None = None,
    on_generate: Callable[[GenerateParams], None] | None = None,
) -> dict:
    def report(percent: int, stage: str) -> None:
        if progress_cb:
            progress_cb(percent, stage)

    report(3, "正在理解你的要求")
    state = merge_slots(slot_state or {}, extract_slots(
        message, history, api_key=api_key, images=images,
    ))
    missing = missing_keys(state)
    if missing:
        reply = (build_natural_followup(message, state, missing, api_key=api_key)
                 or build_followup(missing, state))
        return {"reply": reply, "slot_state": state,
                "questions": [], "done": False}

    _guard(cancel_check)
    params, scope = build_params(state, bank_id, document_id)
    params = params.model_copy(update={"scope": scope, "existing_stems": list(existing_stems or [])})
    if on_generate:
        on_generate(params)
    requested = sum(t.count for t in params.types)
    report(8, f"已确定 {requested} 道题，开始检索知识点")

    def gen_progress(percent: int, stage: str) -> None:
        _guard(cancel_check)
        # 生成阶段占 10~75
        report(10 + int(percent * 0.65), stage)

    try:
        questions = generate_questions(
            params,
            doc_name,
            scope=scope,
            mixed_difficulty=bool(state.get("mixed_difficulty")),
            difficulty_note=str(state.get("difficulty_note") or ""),
            existing_stems=existing_stems,
            api_key=api_key,
            hyde_text=hyde_text,
            retrieve_fn=retrieve_fn,
            progress_cb=gen_progress,
            **cancellation_kwargs((lambda: _guard(cancel_check)) if cancel_check else None),
        )
    except NeedConfirmError as exc:
        # 询问后清掉来源模式槽位，引导用户重新选择；题型数量保留
        state.pop("source_mode", None)
        return {
            "reply": CONFIRM_REPLY.format(
                type_label=exc.type_label, available=exc.available, requested=exc.requested
            ),
            "slot_state": state,
            "questions": [],
            "done": False,
            "generation_error": RunErrorCode.NEED_CONFIRM,
        }
    except ValueError as exc:
        _guard(cancel_check)
        return {"reply": friendly_error(exc), "slot_state": state, "questions": [], "done": True,
                "generation_error": RunErrorCode.GENERATION_ERROR}

    _guard(cancel_check)
    report(78, f"已生成 {len(questions)} 道，正在查重与评估难度")
    return {
        "reply": DONE_REPLY.format(n=len(questions)),
        "slot_state": state,
        "questions": [q.model_dump() for q in questions],
        "done": True,
    }


# ---------------- 创新命题：一次一道，支持图片题型模仿 ----------------

def _creative_missing(state: dict) -> list[str]:
    missing = []
    if not state.get("scope"):
        missing.append("scope")
    types = state.get("types") or []
    if not types or not types[0].get("type"):
        missing.append("types")
    if not state.get("difficulty"):
        missing.append("difficulty")
    return missing


def build_creative_followup(missing: list[str]) -> str:
    from app.services.rag.prompts import CREATIVE_FOLLOWUP_LINES

    lines = [CREATIVE_FOLLOWUP_LINES[k] for k in ("scope", "types", "difficulty") if k in missing]
    numbered = [f"{i}. {line}" for i, line in enumerate(lines, 1)]
    return "\n".join(["生成创新题还需要了解以下信息哦", *numbered, "您可以一次性告诉我"])


def handle_creative(
    bank_id: str,
    document_id: str,
    doc_name: str,
    message: str,
    history: list[dict],
    slot_state: dict,
    existing_stems: list[str] | None = None,
    api_key: str | None = None,
    hyde_text: str | None = None,
    images: list[str] | None = None,
    progress_cb: ProgressCB | None = None,
    cancel_check: CancelCheck | None = None,
    on_generate: Callable[[GenerateParams], None] | None = None,
) -> dict:
    """创新命题：固定单题，题干追求新颖；查重与难度评估复用快速出题中间件。"""

    def report(percent: int, stage: str) -> None:
        if progress_cb:
            progress_cb(percent, stage)

    report(3, "正在理解你的要求")
    state = merge_slots(slot_state or {}, extract_slots(
        message, history, api_key=api_key, images=images,
    ))
    types = state.get("types") or []
    state["types"] = ([{"type": types[0]["type"], "count": 1}]
                      if types and types[0].get("type") else [])
    missing = _creative_missing(state)
    if missing:
        return {"reply": build_creative_followup(missing), "slot_state": state,
                "questions": [], "done": False}

    params, scope = build_params(state, bank_id, document_id)
    params = params.model_copy(update={
        "source_mode": "new", "scope": scope, "existing_stems": list(existing_stems or []),
    })
    _guard(cancel_check)
    if on_generate:
        on_generate(params)
    directive = CREATIVE_SYSTEM_EXTRA
    if state.get("image_note"):
        directive += f"\n参考图片的题型说明：{state['image_note']}"
    report(8, "正在构思创新题")

    def gen_progress(percent: int, stage: str) -> None:
        _guard(cancel_check)
        report(10 + int(percent * 0.65), stage)

    questions = generate_questions(
        params, doc_name, scope=scope, existing_stems=existing_stems,
        api_key=api_key, hyde_text=hyde_text, directive=directive,
        progress_cb=gen_progress,
        **cancellation_kwargs((lambda: _guard(cancel_check)) if cancel_check else None),
    )
    _guard(cancel_check)
    report(78, "正在查重与评估难度")
    return {"reply": DONE_REPLY.format(n=len(questions)), "slot_state": state,
            "questions": [q.model_dump() for q in questions], "done": True}


MAX_REFILL_ROUNDS = 2


def review_with_refill(
    first_pool: list[Question], params: GenerateParams, requested: int,
    existing_stems: list[str] | None,
    review_fn: Callable[[list[Question], GenerateParams, list[str]], tuple[list[Question], object]],
    gen_fn: Callable[[GenerateParams, list[str], ProgressCB], list[Question]],
    progress_cb: ProgressCB | None = None, cancel_check: CancelCheck | None = None,
) -> tuple[list[Question], object, bool]:
    """按各题型实际缺口补齐，累计审核统计与所有已见题干；取消向调用方传播。"""
    from app.services.question_review import ReviewStats, _norm as normalize

    quota: dict[QuestionType, int] = {}
    type_difficulty: dict[QuestionType, Difficulty] = {}
    for item in params.types:
        quota[item.type] = quota.get(item.type, 0) + item.count
        if item.difficulty:
            type_difficulty[item.type] = item.difficulty
    counts = dict.fromkeys(quota, 0)
    accepted: list[Question] = []
    avoid = list(dict[str, None].fromkeys((existing_stems or []) + params.existing_stems))

    seen = {normalize(stem) for stem in avoid if stem}
    stats = ReviewStats()
    pool = list(first_pool)
    last_percent = 78

    def report(percent: int, stage: str) -> None:
        nonlocal last_percent
        _guard(cancel_check)
        last_percent = max(last_percent, min(98, max(0, percent)))
        if progress_cb:
            progress_cb(last_percent, stage)

    for round_no in range(MAX_REFILL_ROUNDS + 1):
        _guard(cancel_check)
        report(78 + round_no * 8, "正在审核题目" if not round_no else "正在审核补齐题目")
        review_params = params.model_copy(update={
            "existing_stems": list(avoid),
            "types": [TypeCount(type=kind, count=target - counts[kind],
                                difficulty=type_difficulty.get(kind))
                      for kind, target in quota.items() if counts[kind] < target],
        })
        passed, current_stats = review_fn(pool, review_params, list(avoid))
        _guard(cancel_check)
        for field in ("duplicates", "repaired", "regenerated", "solved"):
            setattr(stats, field, getattr(stats, field) + getattr(current_stats, field, 0))
        for question in passed:
            stem = normalize(question.stem)
            if stem in seen:
                stats.duplicates += 1
                continue
            seen.add(stem)
            avoid.append(question.stem)
            if (question.type in quota and counts[question.type] < quota[question.type]
                    and len(accepted) < requested):
                accepted.append(question)
                counts[question.type] += 1
        for question in pool:
            if normalize(question.stem) not in seen:
                seen.add(normalize(question.stem))
                avoid.append(question.stem)
        deficits = [TypeCount(type=kind, count=target - counts[kind],
                              difficulty=type_difficulty.get(kind))
                    for kind, target in quota.items() if counts[kind] < target]
        if not deficits or len(accepted) >= requested or round_no == MAX_REFILL_ROUNDS:
            break
        refill_params = params.model_copy(update={"types": deficits, "existing_stems": list(avoid)})
        start = 80 + round_no * 8

        def refill_progress(percent: int, stage: str) -> None:
            report(start + int(min(100, max(0, percent)) * 0.05), stage)

        pool = gen_fn(refill_params, list(avoid), refill_progress)
        _guard(cancel_check)
    report(98, "正在写入题目")
    return accepted, stats, False

"""对话出题编排：槽位抽取 → 缺失追问 → 齐备生成（含 HyDE + 混合检索）。

规划层与执行层的分工见 question_gen：规划层（_plan_points）按知识点范围
制定互不重复的考点蓝图；执行层（_gen_for_type）按蓝图分批并发命制、多轮补齐。
本模块在其上叠加两层任务闭环：生成后的 ValueError 兜底，以及审核剔除后的
自动补齐（review_with_refill），保证高压长任务的数量严格达标。
"""
from typing import Callable

from app.schemas.question import GenerateParams, Question, QuestionType, TypeCount
from app.services.rag.prompts import CREATIVE_SYSTEM_EXTRA
from app.services.rag.question_gen import (
    NeedConfirmError,
    generate_questions,
)
from app.services.rag.slots import build_followup, build_params, extract_slots, merge_slots, missing_keys

DONE_REPLY = "已按你的要求生成完毕，共 {n} 道，已同步到「题目预览」标签页。{context}要调整数量、难度或换一批，直接告诉我。"
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


class ChatCanceled(Exception):
    """用户点了暂停：在阶段检查点抛出，阻止继续生成与落库。"""


def build_result_reply(
    actual: int, requested: int, stats=None, type_label: str | None = None, scope: str | None = None,
) -> str:
    """按审核后的真实结果写回复，数量对不上时说明原因；有语境时回应用户的具体要求。"""
    if actual <= 0:
        return EMPTY_REPLY
    if actual >= requested:
        parts = []
        if scope:
            parts.append(f"知识点范围为「{scope}」")
        if type_label:
            parts.append(f"题型为{type_label}")
        context = ("本次" + "、".join(parts) + "，") if parts else ""
        return DONE_REPLY.format(n=actual, context=context)
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
) -> dict:
    def report(percent: int, stage: str) -> None:
        if progress_cb:
            progress_cb(percent, stage)

    report(3, "正在理解你的要求")
    state = merge_slots(slot_state or {}, extract_slots(message, history, api_key=api_key, images=images))
    missing = missing_keys(state)
    if missing:
        return {"reply": build_followup(missing, state), "slot_state": state,
                "questions": [], "done": False}

    _guard(cancel_check)
    params, scope = build_params(state, bank_id, document_id)
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
            existing_stems=existing_stems,
            api_key=api_key,
            hyde_text=hyde_text,
            retrieve_fn=retrieve_fn,
            progress_cb=gen_progress,
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
        }
    except ValueError as exc:
        # 检索为空、多轮补齐后数量仍不达标等已可读的失败，转成回复而不是 500
        return {"reply": str(exc), "slot_state": state, "questions": [], "done": True}

    _guard(cancel_check)
    report(78, f"已生成 {len(questions)} 道，正在查重与评估难度")
    return {
        "reply": DONE_REPLY.format(n=len(questions), context=""),
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
) -> dict:
    """创新命题：固定单题，题干追求新颖；查重与难度评估复用快速出题中间件。"""

    def report(percent: int, stage: str) -> None:
        if progress_cb:
            progress_cb(percent, stage)

    report(3, "正在理解你的要求")
    state = merge_slots(slot_state or {}, extract_slots(message, history, api_key=api_key, images=images))
    types = state.get("types") or []
    state["types"] = [{"type": types[0]["type"], "count": 1}] if types and types[0].get("type") else []
    missing = _creative_missing(state)
    if missing:
        return {"reply": build_creative_followup(missing), "slot_state": state,
                "questions": [], "done": False}

    params, scope = build_params(state, bank_id, document_id)
    params = params.model_copy(update={"source_mode": "new"})
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
    )
    _guard(cancel_check)
    report(78, "正在查重与评估难度")
    return {"reply": DONE_REPLY.format(n=len(questions), context=""), "slot_state": state,
            "questions": [q.model_dump() for q in questions], "done": True}


# ---------------- 长任务闭环：审核剔除后自动补齐 ----------------

# 审核剔除后的补齐轮次上限；每轮按剩余缺口重新规划考点并分批生成
MAX_REFILL_ROUNDS = 2
# 补齐生成在缺口之外多出的余量比例，弥补补出题可能再次被审核剔除
REFILL_BUFFER_RATIO = 0.2


def split_refill_types(types: list[TypeCount], total_need: int) -> list[TypeCount]:
    """把补齐数量按原题型比例分摊到各题型，保证各题型至少补 1 道。"""
    total = sum(tc.count for tc in types) or 1
    out: list[TypeCount] = []
    allocated = 0
    for index, tc in enumerate(types):
        if index == len(types) - 1:
            count = max(1, total_need - allocated)
        else:
            count = max(1, round(total_need * tc.count / total))
        allocated += count
        out.append(TypeCount(type=tc.type, count=count))
    return out


def review_with_refill(
    first_pool: list[Question],
    params: GenerateParams,
    requested: int,
    existing_stems: list[str] | None,
    review_fn: Callable[[list[Question], GenerateParams, list[str]], tuple[list[Question], object]],
    gen_fn: Callable[[GenerateParams, list[str], Callable[[float, str], None]], list[Question]],
    progress_cb: ProgressCB | None = None,
    cancel_check: CancelCheck | None = None,
) -> tuple[list[Question], object, bool]:
    """审核 + 补齐的长任务闭环：保证最终数量严格达到 requested。

    规划层与执行层产出的题目先经审核剔除（查重、难度不符、知识错配），
    剔除后数量不足时自动进入补齐：按剩余缺口与余量比例重新拆分题型数量，
    复用执行层生成（existing_stems 同步累积，跨轮去重），再送审核。
    review_fn(candidates, params, existing_stems) -> (passed, stats)；
    gen_fn(refill_params, existing_stems, progress) -> questions。
    返回 (accepted, stats, canceled)。
    """

    def report(percent: int, stage: str) -> None:
        if progress_cb:
            progress_cb(percent, stage)

    accepted: list[Question] = []
    avoid = [s for s in (existing_stems or []) if s]
    stats = None
    pool = list(first_pool)
    canceled = False
    for round_no in range(MAX_REFILL_ROUNDS + 1):
        try:
            if cancel_check and cancel_check():
                raise ChatCanceled
            passed, stats = review_fn(pool, params, avoid)
        except ChatCanceled:
            canceled = True
            break
        accepted.extend(passed)
        avoid.extend(q.stem for q in passed)
        if len(accepted) >= requested or round_no >= MAX_REFILL_ROUNDS:
            break
        shortfall = requested - len(accepted)
        need = shortfall + max(1, int(shortfall * REFILL_BUFFER_RATIO))
        refill_params = params.model_copy(update={"types": split_refill_types(params.types, need)})
        report(60, f"审核剔除后需补出 {shortfall} 道（已收 {len(accepted)}/{requested}），正在规划补充考点")

        def gen_progress(percent: float, stage: str) -> None:
            report(60 + int(max(0.0, min(1.0, percent)) * 0.18), stage)

        try:
            pool = gen_fn(refill_params, avoid, gen_progress)
        except ValueError as exc:
            # 补齐轮生成失败：保留已通过的部分，最终数量按实际结果汇报
            report(78, f"补出未完成（{exc}），按已通过数量交付")
            pool = []
            break
        report(78, f"补出 {len(pool)} 道，正在查重与评估难度")
    # 数量与题型分布都严格对齐请求：补齐轮次用尽后累计可能超过请求数，按配额截断
    if len(accepted) > requested:
        quota = {tc.type: tc.count for tc in params.types}
        counts: dict[QuestionType, int] = {}
        trimmed: list[Question] = []
        for question in accepted:
            used = counts.get(question.type, 0)
            if used < quota.get(question.type, 0):
                counts[question.type] = used + 1
                trimmed.append(question)
        accepted = trimmed
    return accepted, stats, canceled

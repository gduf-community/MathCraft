"""对话出题编排：槽位抽取 → 缺失追问 → 齐备生成。"""
from services.question_gen import NeedConfirmError, generate_questions
from services.slots import build_followup, build_params, extract_slots, merge_slots, missing_keys

DONE_REPLY = "题目已生成完成，共 {n} 道，已同步到「题目预览」标签页。还需要生成其他题型吗？"

CONFIRM_REPLY = """材料中「{type_label}」的原题只有 {available} 道，不足 {requested} 道。你可以：
1. 只要原题，把数量改为 {available} 道
2. 保留 {requested} 道，不足的部分用改数据的变式题补齐
3. 改用改背景或全新题的模式
直接回复序号或说明你的选择即可。"""


def handle_chat(
    kb_id: str,
    doc_id: str,
    doc_name: str,
    message: str,
    history: list[dict],
    slot_state: dict,
    existing_stems: list[str] | None = None,
) -> dict:
    state = merge_slots(slot_state or {}, extract_slots(message, history))
    missing = missing_keys(state)
    if missing:
        return {"reply": build_followup(missing), "slot_state": state, "questions": [], "done": False}

    params, scope = build_params(state, kb_id, doc_id)
    try:
        questions = generate_questions(
            params,
            doc_name,
            scope=scope,
            mixed_difficulty=bool(state.get("mixed_difficulty")),
            existing_stems=existing_stems,
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
    return {
        "reply": DONE_REPLY.format(n=len(questions)),
        "slot_state": state,
        "questions": [q.model_dump() for q in questions],
        "done": True,
    }

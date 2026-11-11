"""对话模式意图识别：关键词兜底先行，LLM 输出结构化结果。

分段控制器负责用户显式选模式，这里只产出"建议"，不抢控制权：
- 关键词与当前模式一致时直接放行，不调模型；
- 强关键词指向别的模式时才调 LLM 复核，避免误拦；
- LLM 失败或拿不准时保守放行当前模式。
"""
from app.services.rag.llm import chat_json
from app.services.rag.modes import DEFAULT_MODE, MODES, mode_label
from app.services.rag.prompts import INTENT_SYSTEM

KEYWORD_HINTS: dict[str, tuple[str, ...]] = {
    "generate": (
        "出题", "出一套", "生成题", "一套题", "出一套试卷", "练习题", "习题",
        "几道题", "多少道题", "道选择题", "道判断题", "道填空题", "道计算题",
        "出些", "题量",
    ),
    "qa": (
        "为什么", "是什么", "什么意思", "怎么理解", "如何理解", "解释一下",
        "讲解", "讲讲", "推导一下", "证明过程", "有什么区别", "区别是什么",
        "怎么求", "怎么算", "解题思路", "概念", "答疑", "我不懂",
    ),
    "creative": (
        "创新", "新颖", "一道高质量的题", "出一道题", "新题型", "挑战题",
        "压轴题", "趣味题", "脑洞", "创意",
    ),
    "data": (
        "我的收藏", "收藏的题", "收藏夹", "组卷记录", "学习空间", "我的空间",
        "学生做题", "做题情况", "完成度", "统计一下", "查询我的", "我的试卷",
        "多少份试卷", "数据分析", "删除收藏", "最有意思", "最难的一道",
    ),
}

_FALLBACK = {"slots": {}, "need_confirm": False, "suggested_template": "none", "reason": ""}


def _fallback(mode: str, reason: str) -> dict:
    out = {**_FALLBACK, "intent": mode, "confidence": "high", "reason": reason,
           "suggested_template": mode}
    return out


def keyword_intent(message: str, current_mode: str) -> dict | None:
    """强关键词直接判定；命中当前模式免调模型，其余场景交给 LLM 复核。"""
    hits = {mode: [w for w in words if w in message] for mode, words in KEYWORD_HINTS.items()}
    hits = {mode: words for mode, words in hits.items() if words}
    if current_mode in hits:
        return _fallback(current_mode, f"命中当前模式关键词 {'、'.join(hits[current_mode])}")
    strong = {mode: words for mode, words in hits.items() if len(words) >= 2}
    if len(strong) == 1:
        mode, words = next(iter(strong.items()))
        return {"intent": mode, "confidence": "high", "slots": {}, "need_confirm": False,
                "suggested_template": mode, "reason": f"命中 {'、'.join(words)}"}
    return None


def detect_intent(message: str, current_mode: str, api_key: str | None = None) -> dict:
    """返回 {intent, confidence, slots, need_confirm, suggested_template, reason}。"""
    current = current_mode if current_mode in MODES else DEFAULT_MODE
    kw = keyword_intent(message, current)
    if kw:
        return kw
    try:
        data = chat_json(
            [
                {"role": "system", "content": INTENT_SYSTEM},
                {"role": "user", "content": f"当前模式：{current}（{mode_label(current)}）\n用户消息：{message}"},
            ],
            api_key=api_key,
            thinking_off=True,
        )
    except Exception:  # noqa: BLE001 意图识别失败不阻塞对话，保守放行当前模式
        data = {}
    if not isinstance(data, dict) or data.get("intent") not in MODES:
        return {**_fallback(current, "意图不明确，按当前模式继续"),
                "intent": current, "confidence": "low", "need_confirm": False}
    intent = data["intent"]
    confidence = data.get("confidence") if data.get("confidence") in ("high", "mid", "low") else "low"
    slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    return {
        "intent": intent,
        "confidence": confidence,
        "slots": slots,
        "need_confirm": bool(data.get("need_confirm")) or confidence == "low",
        "suggested_template": intent if intent != current else "none",
        "reason": str(data.get("reason") or "")[:80],
    }

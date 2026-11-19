"""对话出题的槽位状态机：抽取 → 合并 → 缺啥问啥。

抽取交给模型（JSON 输出），只做结构化信息提取；缺槽时先让模型生成自然追问，
失败再回退固定模板。缺槽一律追问，不用默认值补齐。
"""
import logging
import math
import re

from app.schemas.question import Difficulty, GenerateParams, QuestionType, TypeCount
from app.services.rag.llm import chat_json, chat_text
from app.services.rag.prompts import FOLLOWUP_SYSTEM, SLOT_EXTRACT_SYSTEM

logger = logging.getLogger("app.rag.slots")

# 槽位检查顺序即追问顺序。题目来源已不再追问：知识库只存知识点，没有原题可还原。
SLOT_ORDER = ["types", "count", "difficulty", "scope"]

SOURCE_ALIASES = {
    "原题": "original", "书中原题": "original", "书上的": "original",
    "改数据": "variant_data", "换数字": "variant_data", "改数据后的": "variant_data",
    "改背景": "variant_context", "换背景": "variant_context",
    "全新": "new", "新题": "new", "全新的": "new",
}
DIFFICULTY_ALIASES = {"简单": "低", "容易": "低", "基础": "低", "中等": "中", "常规": "中", "难": "高", "很难": "高", "地狱": "地狱"}
# 子串扫描用：按长度降序匹配并消耗原文，避免「中等」里的「中」、「高难」里的「难」被重复命中
DIFFICULTY_TOKENS = (
    ("地狱", "地狱"), ("简单", "低"), ("容易", "低"), ("偏易", "低"), ("较易", "低"),
    ("基础", "低"), ("中等", "中"), ("中档", "中"), ("常规", "中"), ("高难", "高"),
    ("较难", "高"), ("很难", "高"), ("困难", "高"), ("偏难", "高"), ("难题", "高"),
    ("难", "高"), ("高", "高"), ("中", "中"), ("低", "低"),
)
TYPE_ALIASES = {"选择": "single", "单选": "single", "多选": "multiple", "判断": "judge", "填空": "blank", "计算": "compute", "简答": "essay", "解答": "essay"}
TYPE_LABELS = {"single": "选择题", "multiple": "多选题", "judge": "判断题",
               "blank": "填空题", "compute": "计算题", "essay": "简答题"}


def extract_slots(message: str, history: list[dict], api_key: str | None = None,
                  images: list[str] | None = None) -> dict:
    """让模型从用户消息里抽取槽位，未提及的字段为 null；图片以多模态 content 传入。

    history 由调用方传入短期记忆窗口（最近 3-5 轮，见 memory.build_short_term_history），
    此处再做一次防御性截断后格式化为记忆块。
    """
    recent = "\n".join(
        f"{'用户' if h.get('role') == 'user' else '助手'}：{h.get('text', '')}"
        for h in history[-10:]
    )
    prompt = (f"【短期记忆 · 最近对话轮次】\n{recent}\n\n" if recent else "") + f"【当前用户消息】\n{message}"
    if images:
        content: str | list[dict] = [
            {"type": "text", "text": prompt},
            *[{"type": "image_url", "image_url": {"url": img}} for img in images],
        ]
    else:
        content = prompt
    data = chat_json(
        [
            {"role": "system", "content": SLOT_EXTRACT_SYSTEM},
            {"role": "user", "content": content},
        ],
        api_key=api_key,
        thinking_off=True,
    )
    return data if isinstance(data, dict) else {}


def _norm_count(raw: object) -> int | None:
    """只接受 1–100 的整数数值，拒绝布尔值、小数和非有限数。

    高压长任务上限 100：50 道题这类规模由规划层拆批执行，不再在入口拦截。
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if not 1 <= raw <= 100 or not math.isfinite(raw) or int(raw) != raw:
        return None
    return int(raw)


def _norm_types(raw) -> list[dict] | None:
    """把抽取结果归一化为 [{type, count, difficulty}]，非法项丢弃。兼容顶层 type/count 旧写法。"""
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            t_raw, c_raw, d_raw = item, None, None
        else:
            t_raw, c_raw, d_raw = item.get("type"), item.get("count"), item.get("difficulty")
        t = TYPE_ALIASES.get(str(t_raw).strip(), str(t_raw).strip() if t_raw else None)
        try:
            QuestionType(t)
        except ValueError:
            continue
        count = _norm_count(c_raw)
        out.append({"type": t, "count": count, "difficulty": _norm_difficulty(d_raw)})
    return out or None


def _coerce_extracted(extracted: dict) -> dict:
    """兼容模型把题型放在顶层 type/count 的写法。"""
    if extracted.get("types"):
        return extracted
    if extracted.get("type"):
        return {
            **{k: v for k, v in extracted.items() if k not in ("type", "count")},
            "types": [{"type": extracted.get("type"), "count": extracted.get("count")}],
        }
    return extracted


def _norm_source(raw) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    return SOURCE_ALIASES.get(s, s if s in ("original", "variant_data", "variant_context", "new") else None)


def _norm_single(raw: str) -> str | None:
    """归一化单个难度描述段；先查精确别名，再剥修饰词后按长度降序扫同义词。"""
    s = raw.strip()
    direct = DIFFICULTY_ALIASES.get(s, s if s in ("低", "中", "高", "地狱") else None)
    if direct:
        return direct
    cleaned = s.removeprefix("难度").strip("的度请帮我要想出题生成一点些")
    for token, level in sorted(DIFFICULTY_TOKENS, key=lambda pair: -len(pair[0])):
        if token in cleaned:
            return level
    return None


def _norm_difficulty(raw) -> str | None:
    if not raw:
        return None
    return _norm_single(str(raw).strip())


def _levels_in(text: str) -> list[str]:
    """按分隔符切段逐段归一化，返回去重后的难度档序列，顺序即出现顺序。"""
    segments = [seg for seg in re.split(r"[，、,;；\s]+|[和与]", str(text)) if seg.strip()]
    levels = []
    for segment in segments:
        if level := _norm_single(segment):
            levels.append(level)
    return list(dict.fromkeys(levels))


def merge_slots(state: dict, extracted: dict) -> dict:
    """合并新抽取的槽位；types 逐条合并，数量缺失时保持 None 交给追问。"""
    extracted = _coerce_extracted(extracted)
    new = dict(state)
    types = _norm_types(extracted.get("types"))
    if types:
        existing = {t["type"]: dict(t) for t in new.get("types", [])
                    if isinstance(t, dict) and t.get("type") in TYPE_LABELS}
        for t in types:
            old = existing.get(t["type"])
            if old:
                if t["count"]:
                    old["count"] = t["count"]
                if t["difficulty"]:
                    old["difficulty"] = t["difficulty"]
            else:
                existing[t["type"]] = {"type": t["type"], "count": t["count"],
                                       "difficulty": t["difficulty"]}
        new["types"] = list(existing.values())
    if v := _norm_source(extracted.get("source_mode")):
        new["source_mode"] = v
    raw_diff = str(extracted.get("difficulty") or "").strip()
    if raw_diff:
        levels = _levels_in(raw_diff)
        if len(set(levels)) >= 2:
            # 用户一次说了多个难度档：按混合难度处理，保留原始描述供生成指令使用，不再追问
            new["mixed_difficulty"] = True
            new["difficulty_note"] = raw_diff[:120]
            new["difficulty"] = "中" if "中" in levels else levels[-1]
        elif v := _norm_difficulty(raw_diff):
            new["difficulty"] = v
            new.pop("mixed_difficulty", None)
            new.pop("difficulty_note", None)
    if extracted.get("mixed_difficulty") and not new.get("difficulty"):
        new["mixed_difficulty"] = True
    if v := extracted.get("scope"):
        new["scope"] = str(v).strip()
    if v := extracted.get("image_note"):
        new["image_note"] = str(v).strip()[:200]
    total = _norm_count(extracted.get("count"))
    if total is not None:
        new["total_count"] = total
    _apply_total_count(new)
    return new


def _apply_total_count(state: dict) -> None:
    """只有一个题型且未给数量时，用户说的总数就是该题型的数量；多题型不猜分配。"""
    types = state.get("types") or []
    total = _norm_count(state.get("total_count"))
    if (total is not None and len(types) == 1 and isinstance(types[0], dict)
            and _norm_count(types[0].get("count")) is None):
        state["types"] = [{**types[0], "count": total}]
        state.pop("total_count", None)


def _types_complete(state: dict) -> bool:
    types = state.get("types") or []
    return isinstance(types, list) and bool(types) and all(
        isinstance(t, dict) and t.get("type") in TYPE_LABELS for t in types
    )


def _counts_complete(state: dict) -> bool:
    """每个题型都要有明确数量，不接受默认值；只给总数时算已给，等题型确定再分配。"""
    types = state.get("types") or []
    if not types:
        return _norm_count(state.get("total_count")) is not None
    return isinstance(types, list) and all(
        isinstance(t, dict) and _norm_count(t.get("count")) is not None for t in types
    )


def _difficulty_complete(state: dict) -> bool:
    """整体难度与题型级难度任一存在即视为已给；混合难度场景整体难度档必被写入。"""
    if _norm_difficulty(state.get("difficulty")):
        return True
    return any(
        isinstance(t, dict) and _norm_difficulty(t.get("difficulty"))
        for t in state.get("types") or []
    )


def missing_keys(state: dict) -> list[str]:
    missing: list[str] = []
    for key in SLOT_ORDER:
        if key == "types":
            if not _types_complete(state):
                missing.append(key)
        elif key == "count":
            if not _counts_complete(state):
                missing.append(key)
        elif key == "scope" and not str(state.get(key) or "").strip():
            missing.append(key)
        elif key == "difficulty" and not _difficulty_complete(state):
            missing.append(key)
    return missing


FOLLOWUP_LINES = {
    "types": "生成哪些题型（选择题、多选题、判断题、填空题、计算题、简答题）",
    "difficulty": "题目的难度（低、中、高、地狱）",
    "scope": "考查哪些知识点，或书中哪些章节",
}
FOLLOWUP_HEAD = "生成题目还需要了解以下信息哦"
FOLLOWUP_TAIL = "您可以一次性告诉我"


def _count_line(state: dict) -> str:
    total = state.get("total_count")
    types = [t for t in state.get("types") or [] if isinstance(t, dict) and t.get("type")]
    pending = [TYPE_LABELS[t["type"]] for t in types
               if t["type"] in TYPE_LABELS and _norm_count(t.get("count")) is None]
    if pending:
        return "、".join(pending) + "分别多少道"
    if len(types) > 1:
        if total:
            return f"一共 {total} 道，各题型分别多少道"
        return "各题型分别多少道"
    return "生成多少道题"


def build_followup(missing: list[str], state: dict | None = None) -> str:
    """按缺槽生成追问：一行一条，序号连续，已给的信息不再问。"""
    state = state or {}
    lines = [
        _count_line(state) if key == "count" else FOLLOWUP_LINES[key]
        for key in SLOT_ORDER if key in missing
    ]
    numbered = [f"{i}. {line}" for i, line in enumerate(lines, 1)]
    return "\n".join([FOLLOWUP_HEAD, *numbered, FOLLOWUP_TAIL])


def _describe_state(state: dict) -> str:
    types = []
    for t in state.get("types") or []:
        if not isinstance(t, dict) or t.get("type") not in TYPE_LABELS:
            continue
        label = TYPE_LABELS[t["type"]]
        count = _norm_count(t.get("count"))
        if count is not None:
            label += f" {count} 道"
        diff = _norm_difficulty(t.get("difficulty"))
        if diff:
            label += f"（难度{diff}）"
        types.append(label)
    known = []
    if types:
        known.append("题型：" + "、".join(types))
    total = _norm_count(state.get("total_count"))
    if total is not None:
        known.append(f"总题量 {total} 道")
    diff = _norm_difficulty(state.get("difficulty"))
    if diff and not state.get("mixed_difficulty"):
        known.append(f"难度：{diff}")
    if state.get("mixed_difficulty") and state.get("difficulty_note"):
        known.append(f"难度分布：{state['difficulty_note']}")
    if str(state.get("scope") or "").strip():
        known.append(f"知识点范围：{state['scope']}")
    return "；".join(known) if known else "暂无"


def build_natural_followup(
    message: str, state: dict, missing: list[str], api_key: str | None = None,
) -> str | None:
    """让模型结合上下文生成自然追问；未配 key、失败或输出为空时返回 None，
    由调用方回退固定模板。"""
    if not api_key:
        return None
    need = "；".join(
        _count_line(state) if key == "count" else FOLLOWUP_LINES[key]
        for key in SLOT_ORDER if key in missing
    )
    prompt = (
        f"【当前用户消息】\n{message}\n\n【已确认的出题要求】\n{_describe_state(state)}"
        f"\n\n【还缺少的信息】\n{need}"
    )
    try:
        text = chat_text(
            [
                {"role": "system", "content": FOLLOWUP_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            api_key=api_key, temperature=0.4, max_tokens=200, thinking_off=True,
        )
    except Exception as exc:  # 追问是辅助路径，失败回退模板并记日志
        logger.warning("自然追问生成失败，回退模板：%s", exc)
        return None
    return (text or "").strip() or None


def build_params(
    state: dict, bank_id: str, document_id: str,
) -> tuple[GenerateParams, str]:
    """从完整槽位构造 GenerateParams 与 scope。数量必须由用户给出。

    题型级难度优先：types 条目自带难度时写入 TypeCount.difficulty，
    整体难度缺省时取第一个题型难度，再缺省回退中档。
    """
    missing = missing_keys(state)
    if missing:
        raise ValueError("出题信息不完整：" + "、".join(missing))
    types = []
    type_diffs: list[str | None] = []
    for item in state["types"]:
        count = _norm_count(item.get("count"))
        if count is None:
            raise ValueError("每个题型的数量必须是 1–100 的整数")
        tc_diff = _norm_difficulty(item.get("difficulty"))
        type_diffs.append(tc_diff)
        types.append(TypeCount(
            type=QuestionType(item["type"]), count=count,
            difficulty=Difficulty(tc_diff) if tc_diff else None,
        ))

    global_diff = _norm_difficulty(state.get("difficulty")) or next(
        (d for d in type_diffs if d), None,
    )
    params = GenerateParams(
        kb_id=bank_id,
        doc_id=document_id,
        types=types,
        difficulty=Difficulty(global_diff or "中"),
        source_mode=state.get("source_mode", "variant_data"),
    )
    return params, str(state["scope"]).strip()

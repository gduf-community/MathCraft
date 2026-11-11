"""对话出题的槽位状态机：抽取 → 合并 → 缺啥问啥。

追问文案用固定模板，保证换行、按点、带序号；
抽取交给模型（JSON 输出），只做结构化信息提取不做回复生成。
缺槽一律追问，不用默认值补齐。
"""
from app.schemas.question import Difficulty, QuestionType, TypeCount
from app.services.rag.llm import chat_json
from app.services.rag.prompts import SLOT_EXTRACT_SYSTEM

# 槽位检查顺序即追问顺序。题目来源已不再追问：知识库只存知识点，没有原题可还原。
SLOT_ORDER = ["types", "count", "difficulty", "scope"]

SOURCE_ALIASES = {
    "原题": "original", "书中原题": "original", "书上的": "original",
    "改数据": "variant_data", "换数字": "variant_data", "改数据后的": "variant_data",
    "改背景": "variant_context", "换背景": "variant_context",
    "全新": "new", "新题": "new", "全新的": "new",
}
DIFFICULTY_ALIASES = {"简单": "低", "容易": "低", "基础": "低", "中等": "中", "常规": "中", "难": "高", "很难": "高", "地狱": "地狱"}
TYPE_ALIASES = {"选择": "single", "单选": "single", "多选": "multiple", "判断": "judge", "填空": "blank", "计算": "compute", "简答": "essay", "解答": "essay"}


def extract_slots(message: str, history: list[dict], api_key: str | None = None,
                  images: list[str] | None = None) -> dict:
    """让模型从用户消息里抽取槽位，未提及的字段为 null；图片以多模态 content 传入。"""
    recent = "\n".join(f"{'用户' if h.get('role') == 'user' else '助手'}：{h.get('text', '')}" for h in history[-4:])
    prompt = (f"【最近对话】\n{recent}\n\n" if recent else "") + f"【当前用户消息】\n{message}"
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


def _norm_types(raw) -> list[dict] | None:
    """把抽取结果归一化为 [{type, count}]，非法项丢弃。兼容顶层 type/count 旧写法。"""
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            t_raw, c_raw = item, None
        else:
            t_raw, c_raw = item.get("type"), item.get("count")
        t = TYPE_ALIASES.get(str(t_raw).strip(), str(t_raw).strip() if t_raw else None)
        try:
            QuestionType(t)
        except ValueError:
            continue
        count = int(c_raw) if isinstance(c_raw, (int, float)) and int(c_raw) > 0 else None
        out.append({"type": t, "count": count})
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


def _norm_difficulty(raw) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    return DIFFICULTY_ALIASES.get(s, s if s in ("低", "中", "高", "地狱") else None)


def merge_slots(state: dict, extracted: dict) -> dict:
    """合并新抽取的槽位；types 逐条合并，数量缺失时保持 None 交给追问。"""
    extracted = _coerce_extracted(extracted)
    new = dict(state)
    types = _norm_types(extracted.get("types"))
    if types:
        existing = {t["type"]: t for t in new.get("types", []) if isinstance(t, dict)}
        for t in types:
            old = existing.get(t["type"])
            if old:
                if t["count"]:
                    old["count"] = t["count"]
            else:
                existing[t["type"]] = {"type": t["type"], "count": t["count"]}
        new["types"] = list(existing.values())
    if v := _norm_source(extracted.get("source_mode")):
        new["source_mode"] = v
    if v := _norm_difficulty(extracted.get("difficulty")):
        new["difficulty"] = v
        new.pop("mixed_difficulty", None)
    if extracted.get("mixed_difficulty") and not new.get("difficulty"):
        new["mixed_difficulty"] = True
    if v := extracted.get("scope"):
        new["scope"] = str(v).strip()
    if v := extracted.get("image_note"):
        new["image_note"] = str(v).strip()[:200]
    total = extracted.get("count")
    if isinstance(total, (int, float)) and not isinstance(total, bool) and int(total) > 0:
        new["total_count"] = int(total)
    _apply_total_count(new)
    return new


def _apply_total_count(state: dict) -> None:
    """只有一个题型且未给数量时，用户说的总数就是该题型的数量；多题型不猜分配。"""
    types = state.get("types") or []
    total = state.get("total_count")
    if total and len(types) == 1 and not types[0].get("count"):
        types[0]["count"] = int(total)
        state.pop("total_count", None)


def _types_complete(state: dict) -> bool:
    types = state.get("types") or []
    return bool(types) and all(isinstance(t, dict) and t.get("type") for t in types)


def _counts_complete(state: dict) -> bool:
    """每个题型都要有明确数量，不接受默认值；只给总数时算已给，等题型确定再分配。"""
    types = state.get("types") or []
    if not types:
        return bool(state.get("total_count"))
    return all(isinstance(t.get("count"), int) and t["count"] > 0 for t in types)


def missing_keys(state: dict) -> list[str]:
    missing: list[str] = []
    for key in SLOT_ORDER:
        if key == "types":
            if not _types_complete(state):
                missing.append(key)
        elif key == "count":
            if not _counts_complete(state):
                missing.append(key)
        elif not state.get(key):
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


def build_params(state: dict, bank_id: str, document_id: str) -> tuple:
    """从完整槽位构造 GenerateParams 与 scope。数量必须由用户给出。"""
    types = [TypeCount(type=QuestionType(t["type"]), count=int(t["count"])) for t in state["types"]]
    from app.schemas.question import GenerateParams

    params = GenerateParams(
        kb_id=bank_id,
        doc_id=document_id,
        types=types,
        difficulty=Difficulty(state.get("difficulty", "中")),
        source_mode=state.get("source_mode", "variant_data"),
    )
    return params, state.get("scope")

"""对话出题的槽位状态机：抽取 → 合并 → 缺啥问啥。

追问文案用固定模板，保证简洁、按点、带序号；
抽取交给模型（JSON 输出），只做结构化信息提取不做回复生成。
"""
from schemas.question import Difficulty, QuestionType, TypeCount
from services.llm import chat_json
from services.prompts import SLOT_EXTRACT_SYSTEM

# 槽位检查顺序即追问顺序
SLOT_ORDER = ["types", "scope", "source_mode", "difficulty"]

SOURCE_ALIASES = {
    "原题": "original", "书中原题": "original", "书上的": "original",
    "改数据": "variant_data", "换数字": "variant_data", "改数据后的": "variant_data",
    "改背景": "variant_context", "换背景": "variant_context",
    "全新": "new", "新题": "new", "全新的": "new",
}
DIFFICULTY_ALIASES = {"简单": "低", "容易": "低", "基础": "低", "中等": "中", "常规": "中", "难": "高", "很难": "高", "地狱": "地狱"}
TYPE_ALIASES = {"选择": "single", "单选": "single", "多选": "multiple", "判断": "judge", "填空": "blank", "计算": "compute", "简答": "essay", "解答": "essay"}


async def extract_slots(message: str, history: list[dict]) -> dict:
    """让模型从用户消息里抽取槽位，未提及的字段为 null。"""
    recent = "\n".join(f"{'用户' if h.get('role') == 'user' else '助手'}：{h.get('text', '')}" for h in history[-4:])
    prompt = (f"【最近对话】\n{recent}\n\n" if recent else "") + f"【当前用户消息】\n{message}"
    data = await chat_json(
        [
            {"role": "system", "content": SLOT_EXTRACT_SYSTEM},
            {"role": "user", "content": prompt},
        ]
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
    """合并新抽取的槽位；types 逐条合并，count 补齐默认 5。"""
    extracted = _coerce_extracted(extracted)
    new = dict(state)
    types = _norm_types(extracted.get("types"))
    if types:
        existing = {t["type"]: t for t in new.get("types", []) if isinstance(t, dict)}
        for t in types:
            old = existing.get(t["type"])
            if old:
                old["count"] = t["count"] or old.get("count") or 5
            else:
                existing[t["type"]] = {"type": t["type"], "count": t["count"] or 5}
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
    return new


def missing_keys(state: dict) -> list[str]:
    return [k for k in SLOT_ORDER if not state.get(k)]


FOLLOWUP_LINES = {
    "types": "1. 需要哪些题型，各多少道（如选择题 5 道、判断题 3 道）",
    "scope": "2. 题目考查哪些知识点，或者书中哪些章节的内容",
    "source_mode": "3. 题目来源：书中原题、改数据的题、改背景的题，还是全新题",
    "difficulty": "4. 难度：全都很难、就几道难（其余常规），还是整体常规",
}


def build_followup(missing: list[str]) -> str:
    lines = [FOLLOWUP_LINES[k].split(". ", 1)[1] for k in SLOT_ORDER if k in missing]
    numbered = [f"{i}. {line}" for i, line in enumerate(lines, 1)]
    return "请告诉我以下信息：\n" + "\n".join(numbered)


def build_params(state: dict, kb_id: str, doc_id: str) -> tuple:
    """从完整槽位构造 GenerateParams 与 scope。"""
    types = [TypeCount(type=QuestionType(t["type"]), count=int(t.get("count") or 5)) for t in state["types"]]
    from schemas.question import GenerateParams

    params = GenerateParams(
        kb_id=kb_id,
        doc_id=doc_id,
        types=types,
        difficulty=Difficulty(state.get("difficulty", "中")),
        source_mode=state.get("source_mode", "variant_data"),
    )
    return params, state.get("scope")

"""领域模型：与前端 frontend/src/types/index.ts 的 Question 结构严格对齐。"""
import re
from enum import Enum

from pydantic import BaseModel, Field, model_validator

# 选项文本里常见的「A. xxx」前缀
_OPTION_PREFIX = re.compile(r"^([A-Ha-h])[.、．:：]\s*(.+)$")


def _as_dict(value) -> dict:
    """模型有时把蓝图、自检写成一段话，统一收成字典，避免整题被判为非法。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"note": value.strip()} if value.strip() else {}
    if isinstance(value, list):
        return {"items": value}
    return {}


def _as_str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        return [f"{k}：{v}" for k, v in value.items()]
    return []


# 渲染层只解析美元定界符；模型偶发输出 \( \) 与 \[ \]，入库前统一改写
_INLINE_MATH = re.compile(r"\\\((.+?)\\\)", re.S)
_DISPLAY_MATH = re.compile(r"\\\[(.+?)\\\]", re.S)
_CODE_FENCE = re.compile(r"```(?:latex|tex|math)?\s*|\s*```")


def normalize_latex(text: str) -> str:
    """把其他 LaTeX 定界符统一成 $...$ / $$...$$，并剥掉 markdown 代码栅栏。"""
    if not text:
        return text
    if "```" in text:
        text = _CODE_FENCE.sub("", text)
    text = _DISPLAY_MATH.sub(lambda m: "$$" + m.group(1) + "$$", text)
    text = _INLINE_MATH.sub(lambda m: "$" + m.group(1) + "$", text)
    return text


class QuestionType(str, Enum):
    single = "single"      # 选择题
    multiple = "multiple"  # 多选题
    judge = "judge"        # 判断题
    blank = "blank"        # 填空题
    compute = "compute"    # 计算题
    essay = "essay"        # 简答题


class Difficulty(str, Enum):
    low = "低"
    mid = "中"
    high = "高"
    hell = "地狱"


class OptionItem(BaseModel):
    label: str
    text: str


class Question(BaseModel):
    id: str = ""
    type: QuestionType
    score: int = Field(default=5, ge=1, le=100)
    difficulty: Difficulty = Difficulty.mid
    # 题干/选项/答案/解析中的公式一律用 $...$ 包裹的 LaTeX
    stem: str
    options: list[OptionItem] = []
    answer: str
    analysis: str
    knowledgePoint: str = ""
    # 命题阶段写下的蓝图、评分点与自检结果，用于审计与展示
    blueprint: dict = {}
    scoringPoints: list[str] = []
    selfCheck: dict = {}
    # 中间件盲评得到的加权总分（1~5），0 表示未评估
    difficultyScore: float = 0.0
    # 盲评明细：各维分、判定档、缺陷码与建议
    difficultyReview: dict = {}
    starred: bool = False
    docName: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data):
        """兼容模型输出的常见偏差：蓝图/自检写成字符串、选项写成字符串数组、定界符不统一。"""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for key in ("stem", "answer", "analysis"):
            if isinstance(out.get(key), str):
                out[key] = normalize_latex(out[key])
        if isinstance(out.get("options"), list):
            out["options"] = [
                {**item, "text": normalize_latex(item["text"])}
                for item in out["options"]
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ] if all(isinstance(item, dict) for item in out["options"]) else out["options"]
        for key in ("blueprint", "selfCheck", "difficultyReview"):
            if key in out:
                out[key] = _as_dict(out[key])
        if "scoringPoints" in out:
            out["scoringPoints"] = _as_str_list(out["scoringPoints"])
        options = out.get("options")
        if isinstance(options, list) and any(isinstance(item, str) for item in options):
            fixed = []
            for index, item in enumerate(options):
                if isinstance(item, str):
                    label = "ABCDEFGH"[index] if index < 8 else str(index + 1)
                    text = normalize_latex(item.strip())
                    matched = _OPTION_PREFIX.match(text)
                    if matched:
                        label, text = matched.group(1).upper(), matched.group(2).strip()
                    fixed.append({"label": label, "text": text})
                else:
                    fixed.append(item)
            out["options"] = fixed
        return out


class TypeCount(BaseModel):
    type: QuestionType
    count: int = Field(ge=1, le=20)


class GenerateParams(BaseModel):
    kb_id: str
    doc_id: str
    types: list[TypeCount]
    difficulty: Difficulty = Difficulty.mid
    # original=书中原题 variant_data=改数据 variant_context=改背景 new=全新题
    source_mode: str = "variant_data"
    # 知识点或章节范围，用于检索与命题约束
    scope: str = ""
    # 已有题干，用于跨请求去重
    existing_stems: list[str] = []


class ChatRequestBody(BaseModel):
    kb_id: str
    doc_id: str
    message: str
    history: list[dict] = []
    slot_state: dict = {}
    existing_stems: list[str] = []

"""出题请求与响应模型：与前端 Question 结构严格对齐。"""

from typing import Any, Literal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from MathCraft.services.rag.evidence import Evidence


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


class QuestionSource(Evidence):
    relation: Literal["original", "variant_reference", "concept_reference"] = "concept_reference"


class Question(BaseModel):
    id: str = ""
    type: QuestionType
    score: int = Field(default=5, ge=1, le=100)
    difficulty: Difficulty = Difficulty.mid
    # 题干/选项/答案/解析中的公式一律用 $...$ 包裹的 LaTeX
    stem: str
    options: list[OptionItem] = Field(default_factory=list)
    answer: str
    analysis: str
    knowledgePoint: str = ""
    starred: bool = False
    docName: str = ""
    sources: list[QuestionSource] = Field(default_factory=list)
    review_status: Literal["unreviewed", "edited_requires_review", "legacy_unknown"] = "legacy_unknown"


class QuestionUpdate(BaseModel):
    """Editable fields only; source identities cannot be supplied by a client."""
    model_config = ConfigDict(extra="forbid")
    type: QuestionType | None = None
    score: int | None = Field(default=None, ge=1, le=100)
    difficulty: Difficulty | None = None
    stem: str | None = None
    options: list[OptionItem] | None = None
    answer: str | None = None
    analysis: str | None = None
    knowledgePoint: str | None = None


class TypeCount(BaseModel):
    type: QuestionType
    count: int = Field(ge=1, le=20)


class GenerateParams(BaseModel):
    kb_id: str
    doc_id: str
    types: list[TypeCount]
    difficulty: Difficulty = Difficulty.mid
    # original=书中原题 variant_data=改数据 variant_context=改背景 new=全新题
    source_mode: Literal["original", "variant_data", "variant_context", "new"] = "variant_data"
    # 知识点或章节范围，用于检索与命题约束
    scope: str = ""
    # 已有题干，用于跨请求去重
    existing_stems: list[str] = Field(default_factory=list)


class ChatRequestBody(BaseModel):
    kb_id: str
    doc_id: str
    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    slot_state: dict[str, Any] = Field(default_factory=dict)
    existing_stems: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """一轮对话出题的稳定响应。"""

    reply: str
    slot_state: dict[str, Any]
    questions: list[Question]
    done: bool
    error_type: str | None = None

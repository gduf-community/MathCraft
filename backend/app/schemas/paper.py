"""组卷、发布与作答请求及响应模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.question import OptionItem


class PaperModuleBody(BaseModel):
    type: str = Field(pattern="^(single|multiple|judge|blank|compute|essay)$")
    count: int = Field(ge=0)
    total_score: int = Field(ge=0)


class PaperCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    questions: list[str] = Field(min_length=1)
    modules_order: list[PaperModuleBody] | None = None
    space_ids: list[str] = Field(default=[])
    save_to_records: bool = True
    is_published: bool = False
    exam_start: datetime | None = None
    exam_end: datetime | None = None
    allow_review: bool = True
    allow_retake: bool = False


class PaperUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    questions: list[str] | None = None
    modules_order: list[PaperModuleBody] | None = None
    space_ids: list[str] | None = None
    exam_start: datetime | None = None
    exam_end: datetime | None = None
    is_published: bool | None = None
    allow_review: bool | None = None
    allow_retake: bool | None = None


class PaperPublishBody(BaseModel):
    space_ids: list[str] = Field(min_length=1)
    exam_start: datetime | None = None
    exam_end: datetime | None = None


class PaperQuestionRemoveBody(BaseModel):
    paper_question_ids: list[str] = Field(min_length=1)


class PaperBatchDeleteBody(BaseModel):
    paper_ids: list[str] = Field(min_length=1)


class AttemptCreateBody(BaseModel):
    space_id: str | None = None


class AttemptAnswerBody(BaseModel):
    paper_question_id: str = Field(min_length=1)
    choices: list[str] = Field(default=[])
    text: str = ""


class AttemptSubmitBody(BaseModel):
    answers: list[AttemptAnswerBody] = Field(default=[])


class PaperExamWindow(BaseModel):
    """试卷可选作答时间窗。"""

    start: datetime | None
    end: datetime | None


class PaperPublicationRead(BaseModel):
    """单个发布空间的独立停止状态。"""

    space_id: str
    name: str
    stopped: bool
    published_at: datetime


class PaperQuestionRead(BaseModel):
    """试卷题目快照；答案和解析仅在调用方获准时出现。"""

    id: str
    paper_question_id: str
    source_question_id: str | None
    no: int = Field(description="普通载荷连续编号；history=true 时保留原始题号，允许不连续")
    type: str
    score: int
    difficulty: str
    stem: str
    options: list[OptionItem]
    knowledge_point: str
    answer: str | None = None
    analysis: str | None = None


class PaperRead(BaseModel):
    """组卷响应；closed 独立于发布状态，deleted 表示历史保留的删除。"""

    id: str
    name: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    question_count: int
    total_score: int
    status: str
    closed: bool
    deleted: bool
    saved_to_records: bool
    allow_review: bool
    allow_retake: bool
    exam_window: PaperExamWindow | None
    spaces: list[PaperPublicationRead]
    submitted_count: int
    student_count: int
    answered: bool
    modules_order: list[PaperModuleBody]
    questions: list[PaperQuestionRead] | None = None


class AttemptPaperRead(BaseModel):
    """作答页试卷信息；总分取本次作答快照。"""

    id: str
    name: str
    total_score: int
    allow_review: bool
    allow_retake: bool
    exam_window: PaperExamWindow | None
    closed: bool
    deleted: bool
    stopped: bool


class AttemptSpaceRead(BaseModel):
    """空间作答的来源；个人练习不包含空间。"""

    id: str
    name: str


class AttemptQuestionRead(BaseModel):
    """本次作答的题目；答案和解析仅在已交卷且允许复盘时出现。"""

    paper_question_id: str
    no: int = Field(description="作答快照中的原始题号，允许不连续")
    type: str
    score: int
    difficulty: str
    stem: str
    options: list[OptionItem]
    knowledge_point: str
    answer: str | None = None
    analysis: str | None = None


class AttemptRead(BaseModel):
    """作答进度与成绩，包含事务外批卷期间的 grading 状态。"""

    id: str
    status: Literal["answering", "grading", "submitted"]
    score: int | None
    total_score: int
    started_at: datetime
    submitted_at: datetime | None


class AttemptAnswerRead(BaseModel):
    """已保存的学生答案及逐题批卷结果。"""

    paper_question_id: str
    choices: list[str]
    text: str
    score: int
    is_correct: bool
    grading_note: str | None


class AttemptPayloadRead(BaseModel):
    """预览、开始作答、读取进度和复盘共用的完整载荷。"""

    paper: AttemptPaperRead
    space: AttemptSpaceRead | None
    questions: list[AttemptQuestionRead]
    attempt: AttemptRead | None
    answers: list[AttemptAnswerRead]


class AttemptSubmitDetailRead(BaseModel):
    """交卷后的逐题结果；禁止复盘时省略答案和解析。"""

    paper_question_id: str
    score: int
    is_correct: bool
    answer: str | None = None
    analysis: str | None = None


class AttemptSubmitRead(BaseModel):
    """交卷返回的成绩和逐题结果。"""

    attempt_id: str
    score: int
    total_score: int
    detail: list[AttemptSubmitDetailRead]

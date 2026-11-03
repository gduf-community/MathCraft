"""组卷、发布与作答请求模型。"""
from datetime import datetime

from pydantic import BaseModel, Field


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

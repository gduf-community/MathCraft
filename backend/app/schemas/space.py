"""学习空间请求及空间试卷响应模型。"""
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.paper import PaperExamWindow


class SpaceCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    capacity: int = Field(default=50, ge=1, le=500)


class SpaceUpdateBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SpaceJoinBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class SpacePaperRead(BaseModel):
    """学习空间试卷列表，保留独立停止状态、作答统计和催交时间。"""

    id: str
    name: str
    created_at: datetime
    question_count: int
    total_score: int
    status: str
    closed: bool
    deleted: bool
    allow_review: bool
    allow_retake: bool
    exam_window: PaperExamWindow | None
    stopped: bool
    submitted_count: int
    student_count: int
    answered: bool
    last_urge_at: datetime | None

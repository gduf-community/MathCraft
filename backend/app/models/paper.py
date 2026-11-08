"""试卷：组卷快照、空间发布、学生作答与逐题答案。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin, utcnow


class Paper(Base, TimestampMixin):
    __tablename__ = "papers"

    id: Mapped[StrPK]
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)      # draft / published
    saved_to_records: Mapped[bool] = mapped_column(default=True, nullable=False)
    # 交卷后的操作：是否允许查看答案解析 / 是否允许修改答案重新提交
    allow_review: Mapped[bool] = mapped_column(default=True, nullable=False)
    allow_retake: Mapped[bool] = mapped_column(default=False, nullable=False)
    modules_order_json: Mapped[Optional[str]] = mapped_column(Text)
    question_count: Mapped[int] = mapped_column(default=0, nullable=False)
    total_score: Mapped[int] = mapped_column(default=0, nullable=False)
    exam_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    exam_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PaperQuestion(Base):
    __tablename__ = "paper_questions"
    __table_args__ = (
        UniqueConstraint("paper_id", "order_no", name="uq_paper_order"),
    )

    id: Mapped[StrPK]
    paper_id: Mapped[str] = mapped_column(String(40), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    source_question_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("questions.id", ondelete="SET NULL"))
    order_no: Mapped[int] = mapped_column(nullable=False)
    module_type: Mapped[str] = mapped_column(String(16), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[int] = mapped_column(nullable=False)
    difficulty: Mapped[str] = mapped_column(String(8), nullable=False)
    difficulty_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[Optional[str]] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_point: Mapped[Optional[str]] = mapped_column(String(255))


class PaperPublication(Base):
    __tablename__ = "paper_publications"
    __table_args__ = (
        UniqueConstraint("paper_id", "space_id", name="uq_paper_space"),
    )

    id: Mapped[StrPK]
    paper_id: Mapped[str] = mapped_column(String(40), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(40), ForeignKey("study_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    stopped: Mapped[bool] = mapped_column(default=False, nullable=False)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PaperAttempt(Base, TimestampMixin):
    __tablename__ = "paper_attempts"

    id: Mapped[StrPK]
    paper_id: Mapped[str] = mapped_column(String(40), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    space_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("study_spaces.id", ondelete="CASCADE"))
    student_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="answering", nullable=False)  # answering / submitted
    score: Mapped[Optional[int]] = mapped_column()
    total_score: Mapped[int] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "paper_question_id", name="uq_attempt_answer"),
    )

    id: Mapped[StrPK]
    attempt_id: Mapped[str] = mapped_column(String(40), ForeignKey("paper_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    paper_question_id: Mapped[str] = mapped_column(String(40), ForeignKey("paper_questions.id", ondelete="CASCADE"), nullable=False)
    choices_json: Mapped[Optional[str]] = mapped_column(Text)
    text_answer: Mapped[Optional[str]] = mapped_column(Text)
    score: Mapped[int] = mapped_column(default=0, nullable=False)
    is_correct: Mapped[bool] = mapped_column(default=False, nullable=False)
    graded_by: Mapped[Optional[str]] = mapped_column(String(16))     # rule / llm
    grading_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PaperUrge(Base):
    """教师对（试卷, 空间）的催交记录，24 小时内同一组合只允许催交一次。"""

    __tablename__ = "paper_urges"

    id: Mapped[StrPK]
    paper_id: Mapped[str] = mapped_column(String(40), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(40), ForeignKey("study_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UrgeReadState(Base):
    """学生侧催交红点状态：清除时间之后且未单条已读的催交计入未读角标。"""

    __tablename__ = "urge_read_states"

    user_id: Mapped[StrPK]
    cleared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    # 单条已读的催交 id 列表（JSON 数组字符串）
    read_ids: Mapped[Optional[str]] = mapped_column(Text)

"""生成批次与题目。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin, utcnow


class GenerationBatch(Base):
    __tablename__ = "generation_batches"

    id: Mapped[StrPK]
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    bank_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)       # parametric / chat
    params_json: Mapped[Optional[str]] = mapped_column(Text)            # 题型、难度、范围等
    hyde_text: Mapped[Optional[str]] = mapped_column(Text)              # 本次使用的假设段落
    question_count: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="done", nullable=False)  # running / done / failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Question(Base, TimestampMixin):
    __tablename__ = "questions"

    id: Mapped[StrPK]
    batch_id: Mapped[str] = mapped_column(String(40), ForeignKey("generation_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    bank_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)   # single/multiple/judge/blank/compute/essay
    score: Mapped[int] = mapped_column(default=5, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(8), nullable=False)          # 低/中/高/地狱
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[Optional[str]] = mapped_column(Text)                   # [{"label","text"}]
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_point: Mapped[Optional[str]] = mapped_column(String(255))
    source_mode: Mapped[Optional[str]] = mapped_column(String(32))
    retrieval_chunk_ids: Mapped[Optional[str]] = mapped_column(Text)            # 命中 chunk id，逗号分隔
    created_by: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False, index=True)

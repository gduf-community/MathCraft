"""题库、题库成员、文档、文档切片。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin, new_id, utcnow


class Bank(Base, TimestampMixin):
    __tablename__ = "banks"

    id: Mapped[StrPK]
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)   # TK + 年份 + 序号
    creator_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    admin_level: Mapped[str] = mapped_column(String(16), default="super", nullable=False)  # normal / super
    capacity: Mapped[int] = mapped_column(default=200, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)      # active / deleted


class BankMember(Base, TimestampMixin):
    __tablename__ = "bank_members"
    __table_args__ = (
        UniqueConstraint("bank_id", "user_id", name="uq_bank_member"),
        Index("ix_bank_members_user", "user_id"),
    )

    id: Mapped[StrPK]
    bank_id: Mapped[str] = mapped_column(String(40), ForeignKey("banks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)      # owner / admin / member
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active / quit
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# 文档入库状态机：uploaded → parsing → ocr → chunking → embedding → ready / failed
DOC_STATUSES = ("uploaded", "parsing", "ocr", "chunking", "embedding", "ready", "failed")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[StrPK]
    bank_id: Mapped[str] = mapped_column(String(40), ForeignKey("banks.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)     # PDF / DOCX / XLSX / MD
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column()
    is_scanned: Mapped[bool] = mapped_column(default=False, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    text_source: Mapped[Optional[str]] = mapped_column(String(16))     # native / ocr
    status: Mapped[str] = mapped_column(String(16), default="uploaded", nullable=False, index=True)
    stage: Mapped[Optional[str]] = mapped_column(String(255))
    progress: Mapped[int] = mapped_column(default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False)
    ocr_status: Mapped[Optional[str]] = mapped_column(String(16))      # not_needed / pending / running / done / failed
    ocr_task_id: Mapped[Optional[str]] = mapped_column(String(128))
    ocr_result_path: Mapped[Optional[str]] = mapped_column(String(512))
    ocr_error: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    uploader_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_index"),
        Index("ix_chunks_bank", "bank_id"),
    )

    id: Mapped[StrPK]
    bank_id: Mapped[str] = mapped_column(String(40), nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    chunk_type: Mapped[Optional[str]] = mapped_column(String(16))      # question / general / answer
    section: Mapped[Optional[str]] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[str] = mapped_column(Text, nullable=False)          # jieba 分词结果，空格连接
    char_count: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def new_document_id() -> str:
    return new_id("doc")

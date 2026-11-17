"""SQL 持久出题任务；Redis 仅缓存进度和辅助租约。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin


class GenerationTask(Base, TimestampMixin):
    """任务受理、运行凭据和最终批次的权威记录。"""

    __tablename__ = "generation_tasks"
    __table_args__ = (
        Index("ix_generation_tasks_owner_status", "user_id", "status"),
        Index("uq_generation_tasks_owner_request", "user_id", "request_id", unique=True),
    )

    id: Mapped[StrPK]
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    bank_id: Mapped[str] = mapped_column(String(40), nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="parametric")
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(36))
    execution_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[str] = mapped_column(String(256), nullable=False, default="任务已创建")
    batch_id: Mapped[str | None] = mapped_column(String(40))
    result_json: Mapped[str | None] = mapped_column(Text)
    review_json: Mapped[str | None] = mapped_column(Text)
    error_json: Mapped[str | None] = mapped_column(Text)

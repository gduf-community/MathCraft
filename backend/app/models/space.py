"""学习空间与空间成员。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin, utcnow


class StudySpace(Base, TimestampMixin):
    __tablename__ = "study_spaces"

    id: Mapped[StrPK]
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # SP + 年份 + 序号
    creator_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)                        # 1~500
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active / dissolved


class SpaceMember(Base, TimestampMixin):
    __tablename__ = "space_members"
    __table_args__ = (
        UniqueConstraint("space_id", "user_id", name="uq_space_member"),
    )

    id: Mapped[StrPK]
    space_id: Mapped[str] = mapped_column(String(40), ForeignKey("study_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)          # creator / member
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active / left / removed
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

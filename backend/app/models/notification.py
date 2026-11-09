"""站内通知：题库文档入库完成/失败等系统事件，按用户落库，红点计数用。"""
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "read"),
    )

    id: Mapped[StrPK]
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)          # bank_ready / bank_failed
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    bank_id: Mapped[Optional[str]] = mapped_column(String(40))
    document_name: Mapped[Optional[str]] = mapped_column(String(255))
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

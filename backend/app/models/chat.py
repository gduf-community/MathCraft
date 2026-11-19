"""对话会话与消息。"""
from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin, utcnow


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[StrPK]
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bank_id: Mapped[str] = mapped_column(String(40), nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), nullable=False)
    slot_state_json: Mapped[Optional[str]] = mapped_column(Text)     # 槽位持久化快照
    mode: Mapped[str | None] = mapped_column(String(16))
    pending_message: Mapped[str | None] = mapped_column(Text)
    pending_images_json: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(40))
    canceled_run_id: Mapped[str | None] = mapped_column(String(40))
    run_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="idle", server_default="idle",
    )
    run_progress: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    run_stage: Mapped[str] = mapped_column(
        String(256), nullable=False, default="", server_default="",
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session", "session_id", "created_at"),
    )

    id: Mapped[StrPK]
    session_id: Mapped[str] = mapped_column(String(40), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(8), nullable=False)      # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    batch_id: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


ChatRequestStatus = Literal["running", "canceled", "done", "failed", "interrupted"]


class ChatRequest(Base):
    """持久化客户端轮次的取消、发布与执行退出事实。"""

    __tablename__ = "chat_requests"

    session_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True,
    )
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    status: Mapped[ChatRequestStatus] = mapped_column(String(16), nullable=False)
    execution_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    batch_id: Mapped[str | None] = mapped_column(String(40))
    result_json: Mapped[str | None] = mapped_column(Text)

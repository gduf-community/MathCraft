"""用户与按用户的模型配置。"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[StrPK]
    account: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)          # student / teacher
    identity: Mapped[str] = mapped_column(String(16), nullable=False)      # 学生 / 教师
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    gender: Mapped[Optional[str]] = mapped_column(String(8))
    phone: Mapped[Optional[str]] = mapped_column(String(32), unique=True)
    email: Mapped[Optional[str]] = mapped_column(String(128), unique=True)
    user_no: Mapped[Optional[str]] = mapped_column(String(32), unique=True)  # 学号 / 工号
    school: Mapped[Optional[str]] = mapped_column(String(128))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active / disabled


class UserModelSetting(Base):
    __tablename__ = "user_model_settings"

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    deepseek_api_key: Mapped[Optional[str]] = mapped_column(String(128))
    mineru_token: Mapped[Optional[str]] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )

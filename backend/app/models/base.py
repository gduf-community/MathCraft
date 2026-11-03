"""ID 与时间戳公共工具。"""
import secrets
from datetime import datetime, timezone
from typing import Annotated

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 公共列类型简写
StrPK = Annotated[str, mapped_column(String(40), primary_key=True)]
CreatedAt = Annotated[datetime, mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)]
UpdatedAt = Annotated[datetime, mapped_column(
    DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
)]


class TimestampMixin:
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

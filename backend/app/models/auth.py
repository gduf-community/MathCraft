"""认证会话、刷新重放记录、SQL 唯一消费凭证与换绑事务。"""
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[StrPK]
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    auth_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)
    refresh_digest: Mapped[str] = mapped_column(String(64), unique=True)


class RefreshUse(Base):
    __tablename__ = "auth_refresh_uses"

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"), index=True)
    expires_at: Mapped[int] = mapped_column(Integer)


class AuthProof(Base):
    __tablename__ = "auth_proofs"

    challenge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32))
    consumed_at: Mapped[int] = mapped_column(Integer)


class EmailChange(Base):
    __tablename__ = "auth_email_changes"

    id: Mapped[StrPK]
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    old_email: Mapped[str] = mapped_column(String(128))
    new_email: Mapped[str] = mapped_column(String(128))
    auth_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")

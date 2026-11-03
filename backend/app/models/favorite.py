"""收藏分组与收藏。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, utcnow


class FavoriteGroup(Base):
    __tablename__ = "favorite_groups"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_fav_group_name"),)

    id: Mapped[StrPK]
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "question_id", name="uq_favorite"),)

    id: Mapped[StrPK]
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(String(40), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[str] = mapped_column(String(40), ForeignKey("favorite_groups.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

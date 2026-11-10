"""平台检索配置与可恢复的索引切换状态，不包含用户资料。"""
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RagSetting(Base):
    """单行平台配置；活动版本只在新索引全部完成后切换。"""

    __tablename__ = "rag_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(default=0, nullable=False)
    active_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    pending_json: Mapped[str | None] = mapped_column(Text)
    generation: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    rebuild_id: Mapped[str | None] = mapped_column(String(40))
    rebuild_status: Mapped[str] = mapped_column(String(16), default="idle", nullable=False)
    rebuild_progress: Mapped[int] = mapped_column(default=0, nullable=False)
    rebuild_stage: Mapped[str] = mapped_column(String(255), default="尚未重建", nullable=False)
    rebuild_error: Mapped[str | None] = mapped_column(Text)
    mutation_epoch: Mapped[int] = mapped_column(default=0, nullable=False)

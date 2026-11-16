"""跨 SQL、向量及文件存储的持久删除意图；不依赖待删除资源的外键。"""
from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import StrPK, TimestampMixin


class DeletionOperation(Base, TimestampMixin):
    """pending → vectors_deleted → sql_deleted → completed，可从任一阶段幂等恢复。"""

    __tablename__ = "deletion_operations"
    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", name="uq_deletion_resource"),
    )

    id: Mapped[StrPK]
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(40), nullable=False)
    bank_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    generation: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    paths_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

"""平台级 LLM 默认凭据：学校自部署模型接入的单行配置，API Key 静态加密存储。"""
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import UpdatedAt


class PlatformLlmSetting(Base):
    """单行平台模型配置；api_key 以 Fernet 密文存储，主密钥在 data/secret.key。"""

    __tablename__ = "platform_llm_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    encrypted_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    updated_at: Mapped[UpdatedAt]

"""管理员系统模型设置契约，响应永不包含完整凭据。"""
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ServiceFields(BaseModel):
    """可编辑的模型标识与 HTTP 服务地址。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    embedding_model: str = Field(min_length=1, max_length=160)
    embedding_base_url: str = Field(min_length=1, max_length=512)
    rerank_model: str = Field(min_length=1, max_length=160)
    rerank_base_url: str = Field(min_length=1, max_length=512)

    @field_validator("embedding_base_url", "rerank_base_url")
    @classmethod
    def service_url(cls, value: str) -> str:
        """地址禁止内嵌账号、查询串与片段，防止凭据意外回显。"""
        parts = urlsplit(value)
        # 访问 port 同时校验非数字和越界端口，避免保存后才由 HTTP 客户端报错。
        _ = parts.port
        if (parts.scheme not in ("https", "http") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or "?" in value or "#" in value or any(c.isspace() for c in value)):
            raise ValueError("服务地址须为不含凭据、查询参数的 HTTP(S) 地址")
        return value.rstrip("/")


class RagSettingsBody(ServiceFields):
    """空凭据保持原值；revision 用于防止其他管理员的修改被覆盖。"""

    revision: int = Field(ge=0)
    embedding_api_key: SecretStr | None = Field(default=None, max_length=4096)
    rerank_api_key: SecretStr | None = Field(default=None, max_length=4096)


class ServiceTestBody(BaseModel):
    """连接测试只使用本次输入和相应已保存凭据，不保存草稿。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    service: Literal["embedding", "rerank"]
    model: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=1, max_length=512)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    _url = field_validator("base_url")(ServiceFields.service_url.__func__)


class RebuildBody(BaseModel):
    """明确应用当前待处理配置，不接受任意索引或文件路径。"""

    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


class ActiveSettings(ServiceFields):
    embedding_key_configured: bool
    embedding_key_masked: str | None
    rerank_key_configured: bool
    rerank_key_masked: str | None


class PendingSettings(BaseModel):
    embedding_model: str
    embedding_base_url: str
    embedding_key_configured: bool
    embedding_key_masked: str | None


class VectorStoreStatus(BaseModel):
    backend: Literal["chroma"] = "chroma"
    path: str
    available: bool
    message: str


class RebuildStatus(BaseModel):
    status: Literal["idle", "queued", "running", "succeeded", "failed"]
    progress: int
    stage: str
    error: str | None


class RagSettingsResult(BaseModel):
    active: ActiveSettings
    pending: PendingSettings | None
    vector_store: VectorStoreStatus
    rebuild: RebuildStatus
    revision: int


class ServiceTestResult(BaseModel):
    ok: Literal[True] = True
    message: str

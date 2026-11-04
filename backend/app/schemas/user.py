"""个人资料请求模型。"""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    gender: str | None = Field(default=None, pattern="^(男|女)$")
    phone: str | None = Field(default=None, pattern="^1\\d{10}$")
    school: str | None = Field(default=None, max_length=128)

    @field_validator("display_name")
    @classmethod
    def nonempty_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("显示名称不能为空")
        return value.strip() if value is not None else None

"""个人资料请求模型。"""
from pydantic import BaseModel, Field


class UserUpdateBody(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    gender: str | None = Field(default=None, pattern="^(男|女)$")
    phone: str | None = Field(default=None, pattern="^1\\d{10}$")
    email: str | None = Field(default=None, max_length=128)
    school: str | None = Field(default=None, max_length=128)

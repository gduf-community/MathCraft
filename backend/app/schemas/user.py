"""个人资料请求与响应模型。"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    gender: str | None = Field(default=None, pattern="^(男|女)$",
                              description="省略保留原值，null 清除性别")
    phone: str | None = Field(
        default=None, pattern="^1\\d{10}$", description="省略保留原值，null 清除手机号",
    )
    school: str | None = Field(default=None, max_length=128)

    @field_validator("display_name")
    @classmethod
    def nonempty_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("显示名称不能为空")
        return value.strip() if value is not None else None


class UserPayload(BaseModel):
    """真实公开用户字段；历史与未填写的资料允许 null，角色严格限定。"""

    id: str
    account: str
    role: Literal["teacher", "student", "admin"]
    identity: Literal["教师", "学生", "管理员"]
    display_name: str
    gender: str | None
    phone: str | None
    email: str | None
    email_verified: bool
    user_no: str | None
    school: str | None
    avatar_url: str | None
    password_change_recommended: bool = False


class EmailChangeResult(BaseModel):
    """双邮箱验证事务的标识与有效期。"""

    change_id: str
    expires_in: int

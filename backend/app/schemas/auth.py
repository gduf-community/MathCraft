"""认证与模型配置的请求/响应模型。"""
from pydantic import BaseModel, Field, field_validator


ACCOUNT_PATTERN = r"^[\u4e00-\u9fffA-Za-z0-9_.-]+$"


class LoginBody(BaseModel):
    account: str = Field(min_length=1, max_length=64, pattern=ACCOUNT_PATTERN)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("account", mode="before")
    @classmethod
    def strip_account(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ChangePasswordBody(BaseModel):
    """未登录改密（登录页）。"""
    account: str = Field(min_length=1, max_length=64, pattern=ACCOUNT_PATTERN)
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)

    @field_validator("account", mode="before")
    @classmethod
    def strip_account(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PasswordBody(BaseModel):
    """已登录改密。"""
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class ModelSettingsBody(BaseModel):
    # None = 不修改；空字符串 = 清除
    deepseek_api_key: str | None = Field(default=None, max_length=128)
    mineru_token: str | None = Field(default=None, max_length=128)

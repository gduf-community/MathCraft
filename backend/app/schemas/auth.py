"""认证与模型配置的请求/响应模型。"""
from pydantic import BaseModel, Field


class LoginBody(BaseModel):
    account: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)
    role: str = Field(pattern="^(student|teacher)$")


class ChangePasswordBody(BaseModel):
    """未登录改密（登录页）。"""
    account: str = Field(min_length=1, max_length=128)
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)
    role: str = Field(pattern="^(student|teacher)$")


class PasswordBody(BaseModel):
    """已登录改密。"""
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class ModelSettingsBody(BaseModel):
    # None = 不修改；空字符串 = 清除
    deepseek_api_key: str | None = Field(default=None, max_length=128)
    mineru_token: str | None = Field(default=None, max_length=128)

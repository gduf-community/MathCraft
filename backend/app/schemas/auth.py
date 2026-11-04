"""认证输入：严格拒绝多余字段与安全资料旁路。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.auth import normalize_email, normalize_user_no, validate_password

Role = Literal["teacher", "student"]
Purpose = Literal["register", "login", "reset_password", "email_change_old", "email_change_new"]


class AuthBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyBody(AuthBody):
    """Cookie 认证请求必须提供 JSON 对象，不接受表单或任意原始正文。"""


class EmailBody(AuthBody):
    email: str = Field(max_length=128)
    _normalize_email = field_validator("email")(normalize_email)


class EmailCodeBody(EmailBody):
    purpose: Purpose
    turnstile_token: str = Field(min_length=1, max_length=2048)
    change_id: str | None = Field(default=None, min_length=1, max_length=64)


class CodeBody(EmailBody):
    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(pattern=r"^\d{6}$")


class RegisterBody(CodeBody):
    password: str
    confirm_password: str
    display_name: str = Field(min_length=1, max_length=64)
    role: Role
    user_no: str | None = None
    _password = field_validator("password")(validate_password)
    _user_no = field_validator("user_no")(normalize_user_no)

    @field_validator("display_name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("显示名称不能为空")
        return value.strip()

    @model_validator(mode="after")
    def passwords_match(self) -> "RegisterBody":
        if self.password != self.confirm_password:
            raise ValueError("两次密码不一致")
        return self


class EmailLoginBody(CodeBody):
    role: Role


class PasswordLoginBody(AuthBody):
    user_no: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    role: Role
    turnstile_token: str = Field(min_length=1, max_length=2048)

    @field_validator("user_no")
    @classmethod
    def clean_user_no(cls, value: str) -> str:
        result = normalize_user_no(value)
        if result is None:
            raise ValueError("学工号不能为空")
        return result


class NewPasswordBody(AuthBody):
    new_password: str
    confirm_password: str
    _password = field_validator("new_password")(validate_password)

    @model_validator(mode="after")
    def passwords_match(self) -> "NewPasswordBody":
        if self.new_password != self.confirm_password:
            raise ValueError("两次密码不一致")
        return self


class ResetPasswordBody(CodeBody, NewPasswordBody):
    pass


class PasswordBody(NewPasswordBody):
    old_password: str = Field(min_length=1, max_length=128)


class EmailChangeBody(AuthBody):
    new_email: str = Field(max_length=128)
    _email = field_validator("new_email")(normalize_email)


class EmailCommitBody(AuthBody):
    change_id: str = Field(min_length=1, max_length=64)
    old_challenge_id: str = Field(min_length=1, max_length=64)
    old_code: str = Field(pattern=r"^\d{6}$")
    new_challenge_id: str = Field(min_length=1, max_length=64)
    new_code: str = Field(pattern=r"^\d{6}$")


class UserNoBody(AuthBody):
    user_no: str | None
    current_password: str = Field(min_length=1, max_length=128)
    _user_no = field_validator("user_no")(normalize_user_no)


class ModelSettingsBody(BaseModel):
    # None = 不修改；空字符串 = 清除
    deepseek_api_key: str | None = Field(default=None, max_length=128)
    mineru_token: str | None = Field(default=None, max_length=128)

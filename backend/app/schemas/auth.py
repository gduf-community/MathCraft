"""认证请求与响应契约：严格限制输入并描述真实输出。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.user import UserPayload
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


class AuthConfig(BaseModel):
    """公开认证能力与双提交 CSRF 令牌，不包含服务端密钥。"""

    site_key: str
    csrf_token: str
    methods: list[Literal["email_code", "user_no_password"]]
    development_accounts_enabled: bool
    available: bool


class EmailCodeResult(BaseModel):
    """发码统一受理结果，不泄露邮箱是否已注册。"""

    challenge_id: str
    expires_in: int
    retry_after: int


class LoginResult(BaseModel):
    """注册、登录与刷新共用的短期访问凭证和用户资料。"""

    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    user: UserPayload


class CurrentUserResult(BaseModel):
    """当前登录用户，保持既有 user 外层对象。"""

    user: UserPayload


class DevelopmentAccount(BaseModel):
    """仅受控开发环境提供的示例账号。"""

    role: Role
    user_no: str
    password: str


class ErrorDetail(BaseModel):
    """实际业务错误；额外上下文保持兼容，不返回请求输入。"""

    model_config = ConfigDict(extra="allow")
    code: str
    message: str


class ErrorResponse(BaseModel):
    """统一脱敏错误外层，422 不使用默认验证错误数组。"""

    detail: ErrorDetail

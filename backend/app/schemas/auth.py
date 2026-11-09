"""认证请求与响应契约：严格限制输入并描述真实输出。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.user import UserPayload
from app.services.auth import normalize_email, normalize_user_no, validate_password

ACCOUNT_PATTERN = r"^[A-Za-z0-9_.-]+$"

Role = Literal["teacher", "student"]
Purpose = Literal["login", "reset_password", "email_bind", "email_change_old", "email_change_new"]


class AuthBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyBody(AuthBody):
    """Cookie 认证请求必须提供 JSON 对象，不接受表单或任意原始正文。"""


class EmailBody(AuthBody):
    email: str = Field(max_length=128)
    _normalize_email = field_validator("email")(normalize_email)


class EmailCodeBody(EmailBody):
    purpose: Purpose
    turnstile_token: str = Field(default="", max_length=2048)
    change_id: str | None = Field(default=None, min_length=1, max_length=64)


class CodeBody(EmailBody):
    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(pattern=r"^\d{6}$")


class EmailLoginBody(CodeBody):
    """邮箱所有权校验通过后由服务端确定身份。"""


class AccountLoginBody(AuthBody):
    """所有启用账号均可使用账号密码登录，兼容历史账号字符。"""

    account: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    turnstile_token: str = Field(default="", max_length=2048)

    @field_validator("account")
    @classmethod
    def clean_account(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("登录账号不能为空")
        return value.strip()


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


class CurrentPasswordBody(AuthBody):
    """敏感操作需要当前账号密码。"""

    current_password: str = Field(min_length=1, max_length=128)


class EmailBindingBody(CodeBody, CurrentPasswordBody):
    """首次绑定或验证历史未验证邮箱，不替代已验证邮箱的换绑流程。"""


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
    turnstile_enabled: bool
    csrf_token: str
    methods: list[Literal["account_password", "email_code"]]
    admin_contact: str = "请联系本校或平台管理员"
    development_accounts_enabled: bool
    available: bool


class EmailCodeResult(BaseModel):
    """发码统一受理结果，不泄露邮箱是否已注册。"""

    challenge_id: str
    expires_in: int
    retry_after: int


class LoginResult(BaseModel):
    """登录与刷新共用的短期访问凭证和用户资料。"""

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
    account: str
    password: str


class ErrorDetail(BaseModel):
    """实际业务错误；额外上下文保持兼容，不返回请求输入。"""

    model_config = ConfigDict(extra="allow")
    code: str
    message: str


class ErrorResponse(BaseModel):
    """统一脱敏错误外层，422 不使用默认验证错误数组。"""

    detail: ErrorDetail

"""管理员账号与平台信息契约。"""
from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import ACCOUNT_PATTERN


class AccountCreateBody(BaseModel):
    account: str = Field(min_length=1, max_length=64, pattern=ACCOUNT_PATTERN)
    display_name: str = Field(min_length=1, max_length=64)
    role: str = Field(pattern="^(admin|teacher|student)$")
    password: str = Field(min_length=6, max_length=128)

    @field_validator("account", mode="before")
    @classmethod
    def strip_account(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("display_name", mode="before")
    @classmethod
    def strip_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AccountDisplayNameBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)

    @field_validator("display_name", mode="before")
    @classmethod
    def strip_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AccountPasswordBody(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class AccountListItem(BaseModel):
    id: str
    account: str
    display_name: str
    role: str
    identity: str
    status: str
    created_at: object


class PlatformOverview(BaseModel):
    admin_contact: str
    accounts: dict[str, int]
    resources: dict[str, int]
    task_status_counts: dict[str, int]
    tasks: list[dict[str, object]]

"""管理员账号与平台信息契约。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.auth import validate_password

ACCOUNT_PATTERN = r"^[A-Za-z0-9_.-]+$"


class AccountCreateBody(BaseModel):
    account: str = Field(min_length=1, max_length=64, pattern=ACCOUNT_PATTERN)
    display_name: str = Field(min_length=1, max_length=64)
    role: str = Field(pattern="^(admin|teacher|student)$")
    password: str = Field(min_length=8, max_length=64)
    _password = field_validator("password")(validate_password)

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
    password: str = Field(min_length=8, max_length=64)
    _password = field_validator("password")(validate_password)


class AccountListItem(BaseModel):
    id: str
    account: str
    display_name: str
    role: str
    identity: str
    status: str
    created_at: datetime
    password_change_recommended: bool


class PersistedBatchItem(BaseModel):
    """已持久化批次；当前模型没有完成时间，不从创建时间推导。"""

    id: str
    type: str
    status: str
    created_at: datetime
    completed_at: None = None


class PlatformOverview(BaseModel):
    admin_contact: str
    accounts: dict[str, int]
    resources: dict[str, int]
    task_status_counts: dict[str, int]
    task_scope: Literal["persisted_generation_batches"]
    task_total: int
    recent_task_limit: Literal[50]
    tasks: list[PersistedBatchItem]

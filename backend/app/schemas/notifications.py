"""站内通知的请求模型。"""
from pydantic import BaseModel, Field


class NotificationReadBody(BaseModel):
    ids: list[str] | None = Field(default=None, description="不传或为空则标记全部已读")

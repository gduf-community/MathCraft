"""V2 管理员运行查询契约；空值与 unknown 保留原有事实语义。"""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator,
)
from typing_extensions import Self

OpsStatus = Literal["accepted", "running", "completed", "failed", "canceled", "unknown"]
OpsEntrypoint = Literal["parameterized", "conversation"]
OpsId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


def as_utc(value: datetime) -> datetime:
    """SQLite 返回无时区时间时按台账约定解释为 UTC，响应统一带时区。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


UtcTimestamp = Annotated[datetime, AfterValidator(as_utc)]


class OpsModel(BaseModel):
    """拒绝意外字段，避免运行正文或内部配置扩散到查询响应。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)


class OpsWindow(OpsModel):
    """按受理时间筛选的左闭右开区间。"""

    from_: UtcTimestamp = Field(alias="from")
    to: UtcTimestamp
    time_basis: Literal["accepted_at"] = "accepted_at"


class OpsFilters(OpsModel):
    """概览、列表共用精确匹配条件；不接受旧版 cursor 或质量字段。"""

    from_: AwareDatetime | None = Field(default=None, alias="from")
    to: AwareDatetime | None = None
    owner_user_id: OpsId | None = None
    entrypoint: OpsEntrypoint | None = None
    status: OpsStatus | None = None
    session_id: OpsId | None = None
    task_id: OpsId | None = None
    batch_id: OpsId | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """显式时间区间必须非空；省略值在单次请求的时钟下解析。"""
        if self.from_ is not None and self.to is not None and self.from_ >= self.to:
            raise ValueError("from must precede to")
        return self

    def window(self, now: datetime) -> OpsWindow:
        """未给 to 使用当前 UTC；未给 from 使用 to 前 24 小时。"""
        end = as_utc(self.to if self.to is not None else now)
        try:
            start = as_utc(self.from_) if self.from_ is not None else end - timedelta(days=1)
        except OverflowError as exc:
            raise ValueError("invalid time window") from exc
        if start >= end:
            raise ValueError("from must precede to")
        return OpsWindow.model_validate({"from": start, "to": end})


class OpsRunsQuery(OpsFilters):
    """受限 offset 分页；同一受理时间以 run_id 倒序作为唯一排序键。"""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2_147_483_647)


class OpsRun(OpsModel):
    """最小运行事实投影；不包含正文、凭据、心跳推断或质量结论。"""

    run_id: OpsId
    entrypoint: OpsEntrypoint
    owner_user_id: OpsId
    session_id: OpsId | None
    task_id: OpsId | None
    bank_id: OpsId | None
    document_id: OpsId | None
    batch_id: OpsId | None
    status: OpsStatus
    requested_count: int | None = Field(ge=1, strict=True)
    delivered_count: int | None = Field(ge=0, strict=True)
    error_code: str | None
    accepted_at: UtcTimestamp
    started_at: UtcTimestamp | None
    finished_at: UtcTimestamp | None
    last_observed_at: UtcTimestamp | None


class OpsStatusCounts(OpsModel):
    """六个状态的已记录行数；unknown 独立计数，不推断成功或失败。"""

    accepted: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    canceled: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)


class OpsPage(OpsModel):
    """分页不承诺不同请求之间的历史快照。"""

    limit: int
    offset: int
    has_more: bool


class OpsResponse(OpsModel):
    """显式区分已移除的 v1 响应。"""

    schema_version: Literal["v2"] = "v2"
    generated_at: UtcTimestamp


class OpsOverview(OpsResponse):
    """概览只聚合当前 SQL 台账，最近记录最多 10 条。"""

    window: OpsWindow
    total_runs: int = Field(ge=0)
    status_counts: OpsStatusCounts
    recent_runs: list[OpsRun]


class OpsRuns(OpsResponse):
    """管理员运行列表。"""

    window: OpsWindow
    items: list[OpsRun]
    page: OpsPage


class OpsRunDetail(OpsResponse):
    """基本详情与列表共用最小运行事实，不查询业务正文。"""

    run: OpsRun

"""出题运行摘要：只保存结构化事实，不保存业务正文。"""
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db import Base
from app.models.base import StrPK


class RunEntrypoint(StrEnum):
    """运行所属的两类出题入口。"""

    CONVERSATION = "conversation"
    PARAMETERIZED = "parameterized"


class RunStatus(StrEnum):
    """运行事实状态；unknown 不等同于执行失败。"""

    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class RunErrorCode(StrEnum):
    """有限安全分类；调用方不得传入异常、回复或模型正文。"""

    NEED_CONFIRM = "NEED_CONFIRM"
    MODEL_ERROR = "MODEL_ERROR"
    RETRIEVAL_ERROR = "RETRIEVAL_ERROR"
    GENERATION_ERROR = "GENERATION_ERROR"
    NO_PERSISTABLE_QUESTIONS = "NO_PERSISTABLE_QUESTIONS"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"
    TASK_SUBMISSION_ERROR = "TASK_SUBMISSION_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    USER_CANCELED = "USER_CANCELED"
    EXECUTION_INTERRUPTED = "EXECUTION_INTERRUPTED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class UTCDateTime(TypeDecorator[datetime]):
    """写入时统一 UTC，补回 SQLite DateTime 丢失的时区信息。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self) -> type[datetime]:
        """供字段类型内省识别运行时间的 Python 类型。"""
        return datetime

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError("运行时间必须带时区")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(
            timezone.utc
        )


class OpsRun(Base):
    """一次实际出题受理；资源 ID 是快照，不随资源删除级联消失。"""

    __tablename__ = "ops_runs"
    __table_args__ = (
        CheckConstraint("entrypoint IN ('conversation', 'parameterized')", name="ck_ops_entry"),
        CheckConstraint(
            "status IN ('accepted', 'running', 'completed', 'failed', 'canceled', 'unknown')",
            name="ck_ops_status",
        ),
        CheckConstraint(
            "requested_count > 0 AND requested_count = CAST(requested_count AS INTEGER)",
            name="ck_ops_requested",
        ),
        CheckConstraint(
            "delivered_count IS NULL OR (delivered_count >= 0 "
            "AND delivered_count = CAST(delivered_count AS INTEGER))", name="ck_ops_delivered",
        ),
        CheckConstraint(
            "length(run_id) BETWEEN 1 AND 40 AND length(owner_user_id) BETWEEN 1 AND 40 "
            "AND length(bank_id) BETWEEN 1 AND 40 AND length(document_id) BETWEEN 1 AND 40 "
            "AND (session_id IS NULL OR length(session_id) BETWEEN 1 AND 40) "
            "AND (task_id IS NULL OR length(task_id) BETWEEN 1 AND 40) "
            "AND (batch_id IS NULL OR length(batch_id) BETWEEN 1 AND 40)",
            name="ck_ops_identifiers",
        ),
        CheckConstraint(
            "(entrypoint = 'conversation' AND session_id IS NOT NULL AND task_id IS NULL) "
            "OR (entrypoint = 'parameterized' AND session_id IS NULL)",
            name="ck_ops_context",
        ),
        CheckConstraint(
            "(status = 'completed' AND batch_id IS NOT NULL AND delivered_count IS NOT NULL "
            "AND started_at IS NOT NULL AND error_code IS NULL) "
            "OR (status <> 'completed' AND batch_id IS NULL)", name="ck_ops_batch",
        ),
        CheckConstraint(
            "(status IN ('completed', 'failed', 'canceled') AND finished_at IS NOT NULL) "
            "OR (status IN ('accepted', 'running', 'unknown') AND finished_at IS NULL)",
            name="ck_ops_finished",
        ),
        CheckConstraint(
            "(status <> 'accepted' OR started_at IS NULL) "
            "AND (status <> 'running' OR started_at IS NOT NULL)", name="ck_ops_started",
        ),
        CheckConstraint(
            "(status IN ('accepted', 'running', 'unknown') AND delivered_count IS NULL) "
            "OR status = 'completed' OR (status IN ('failed', 'canceled') "
            "AND delivered_count IS NOT NULL AND delivered_count = 0)",
            name="ck_ops_count_evidence",
        ),
        CheckConstraint(
            "(status IN ('accepted', 'running', 'completed') AND error_code IS NULL) "
            "OR (status = 'failed' AND error_code IS NOT NULL "
            "AND error_code IN ('NEED_CONFIRM', 'MODEL_ERROR', "
            "'RETRIEVAL_ERROR', 'GENERATION_ERROR', 'NO_PERSISTABLE_QUESTIONS', "
            "'PERSISTENCE_ERROR', 'TASK_SUBMISSION_ERROR', 'EXECUTION_ERROR')) "
            "OR (status = 'canceled' AND error_code IS NOT NULL AND error_code = 'USER_CANCELED') "
            "OR (status = 'unknown' AND error_code IS NOT NULL "
            "AND error_code IN ('EXECUTION_INTERRUPTED', 'OUTCOME_UNKNOWN'))",
            name="ck_ops_error",
        ),
        CheckConstraint(
            "last_observed_at >= accepted_at "
            "AND (started_at IS NULL OR (started_at >= accepted_at "
            "AND last_observed_at >= started_at)) "
            "AND (finished_at IS NULL OR (finished_at >= accepted_at "
            "AND last_observed_at >= finished_at "
            "AND (started_at IS NULL OR finished_at >= started_at)))", name="ck_ops_time",
        ),
        Index("ix_ops_runs_time", "accepted_at", "run_id"),
        Index("ix_ops_runs_owner_time", "owner_user_id", "accepted_at"),
        Index("ix_ops_runs_status_time", "status", "accepted_at"),
        Index("ix_ops_runs_session", "session_id"),
    )

    run_id: Mapped[StrPK]
    entrypoint: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[str | None] = mapped_column(String(40))
    task_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    bank_id: Mapped[str] = mapped_column(String(40), nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    delivered_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

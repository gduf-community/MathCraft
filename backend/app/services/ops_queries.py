"""只读 SQL 查询；复用甲注册的正式模型，不声明或反射第二份 ops_runs。"""
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Table, func, select, true
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.db import Base
from app.schemas.ops import (
    OpsFilters, OpsOverview, OpsPage, OpsRun, OpsRunDetail, OpsRuns, OpsRunsQuery,
    OpsStatusCounts, OpsWindow,
)

RUN_FIELDS = tuple(OpsRun.model_fields)
STATUS_FIELDS = tuple(OpsStatusCounts.model_fields)
RECENT_LIMIT = 10
# 显式同步甲 RunErrorCode 的安全分类；新增枚举须审查后更新，禁止透传任意字符串。
SAFE_ERROR_CODES = frozenset({
    "NEED_CONFIRM", "MODEL_ERROR", "RETRIEVAL_ERROR", "GENERATION_ERROR",
    "NO_PERSISTABLE_QUESTIONS", "PERSISTENCE_ERROR", "TASK_SUBMISSION_ERROR",
    "EXECUTION_ERROR", "USER_CANCELED", "EXECUTION_INTERRUPTED", "OUTCOME_UNKNOWN",
})


class OpsDataUnavailable(Exception):
    """台账尚未接入、不可查询或不满足最小数据契约。"""


def registered_ops_table() -> Table:
    """只接受公共 ORM registry 中已有的 ops_runs，不加载推测的模型文件。"""
    tables = {
        mapper.local_table for mapper in Base.registry.mappers
        if isinstance(mapper.local_table, Table) and mapper.local_table.name == "ops_runs"
    }
    if len(tables) != 1:
        raise OpsDataUnavailable("formal ops_runs model is not registered")
    return tables.pop()


@contextmanager
def _result_boundary() -> Iterator[None]:
    """Enum 的读取解码可直接抛 LookupError；只保护 SQL 执行和结果物化。"""
    try:
        yield
    except LookupError as exc:
        raise OpsDataUnavailable("ops result could not be decoded") from exc


@contextmanager
def _query_boundary() -> Iterator[None]:
    try:
        yield
    except (SQLAlchemyError, ValueError, TypeError, OverflowError) as exc:
        # 不把 SQL、参数、连接信息或无效行值附加到面向调用方的消息。
        raise OpsDataUnavailable("ops query could not be completed") from exc


class OpsQueryService:
    """在传入会话上执行 SELECT；不 flush、commit、迁移或回填生命周期。"""

    def __init__(self, db: Session, table: Table) -> None:
        if not set(RUN_FIELDS).issubset(table.c.keys()):
            raise OpsDataUnavailable("ops_runs columns do not match V2")
        if list(table.primary_key.columns.keys()) != ["run_id"]:
            raise OpsDataUnavailable("ops_runs must have a unique run_id primary key")
        for name in RUN_FIELDS:
            expected = datetime if name.endswith("_at") else (
                int if name.endswith("_count") else str
            )
            try:
                compatible = issubclass(table.c[name].type.python_type, expected)
            except (NotImplementedError, TypeError):
                compatible = False
            if not compatible:
                raise OpsDataUnavailable("ops_runs column types do not match V2")
        self.db = db
        self.table = table

    def _conditions(self, query: OpsFilters, window: OpsWindow) -> list[ColumnElement[bool]]:
        columns = self.table.c
        conditions = [columns.accepted_at >= window.from_, columns.accepted_at < window.to]
        for name in ("owner_user_id", "entrypoint", "status", "session_id", "task_id", "batch_id"):
            value = getattr(query, name)
            if value is not None:
                conditions.append(columns[name] == value)
        return conditions

    @staticmethod
    def _run(row: RowMapping) -> OpsRun:
        payload = {name: row[name] for name in RUN_FIELDS}
        code = payload["error_code"]
        if code is not None and (not isinstance(code, str) or code not in SAFE_ERROR_CODES):
            payload["error_code"] = "UNKNOWN"
        return OpsRun.model_validate(payload)

    def overview(self, query: OpsFilters, window: OpsWindow, now: datetime) -> OpsOverview:
        """单条 SQL 同时取得聚合与最近记录，避免两次读取间的计数漂移。"""
        with self.db.no_autoflush, _query_boundary():
            filtered = select(*(self.table.c[name] for name in RUN_FIELDS)).where(
                *self._conditions(query, window)
            ).cte("ops_filtered_runs")
            stats = select(
                func.count().label("total_runs"),
                *(func.count().filter(filtered.c.status == name).label(name)
                  for name in STATUS_FIELDS),
            ).select_from(filtered).cte("ops_counts")
            recent = select(filtered).order_by(
                filtered.c.accepted_at.desc(), filtered.c.run_id.desc(),
            ).limit(RECENT_LIMIT).subquery("ops_recent")
            statement = select(stats, recent).select_from(stats.outerjoin(recent, true())).order_by(
                recent.c.accepted_at.desc(), recent.c.run_id.desc(),
            )
            with _result_boundary():
                rows = self.db.execute(statement).mappings().all()
            counts = OpsStatusCounts.model_validate({name: rows[0][name] for name in STATUS_FIELDS})
            total = rows[0]["total_runs"]
            if sum(counts.model_dump().values()) != total:
                raise OpsDataUnavailable("ops_runs contains an invalid status")
            return OpsOverview(
                generated_at=now, window=window, total_runs=total, status_counts=counts,
                recent_runs=[self._run(row) for row in rows if row["run_id"] is not None],
            )

    def list_runs(self, query: OpsRunsQuery, window: OpsWindow, now: datetime) -> OpsRuns:
        """使用 limit + 1 判断后续页；排序键保持唯一且稳定。"""
        with self.db.no_autoflush, _query_boundary():
            statement = select(*(self.table.c[name] for name in RUN_FIELDS)).where(
                *self._conditions(query, window)
            ).order_by(self.table.c.accepted_at.desc(), self.table.c.run_id.desc()).limit(
                query.limit + 1
            ).offset(query.offset)
            with _result_boundary():
                rows = self.db.execute(statement).mappings().all()
            return OpsRuns(
                generated_at=now, window=window,
                items=[self._run(row) for row in rows[:query.limit]],
                page=OpsPage(
                    limit=query.limit, offset=query.offset, has_more=len(rows) > query.limit,
                ),
            )

    def get_run(self, run_id: str, now: datetime) -> OpsRunDetail | None:
        """按主键读取摘要，不进行时间窗口过滤或正文关联查询。"""
        with self.db.no_autoflush, _query_boundary():
            statement = select(*(self.table.c[name] for name in RUN_FIELDS)).where(
                self.table.c.run_id == run_id,
            )
            with _result_boundary():
                row = self.db.execute(statement).mappings().one_or_none()
            return None if row is None else OpsRunDetail(generated_at=now, run=self._run(row))

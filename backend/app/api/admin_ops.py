"""V2 管理员运行概览、列表与基本详情；只读且不依赖 Phoenix。"""
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin
from app.errors import AppError
from app.schemas.auth import ErrorResponse
from app.schemas.ops import (
    OpsFilters, OpsId, OpsOverview, OpsRunDetail, OpsRuns, OpsRunsQuery, OpsWindow,
)
from app.services.ops_queries import OpsDataUnavailable, OpsQueryService, registered_ops_table

router = APIRouter(
    prefix="/api/admin/ops", tags=["admin-ops"], dependencies=[Depends(require_admin)],
    responses={
        401: {"model": ErrorResponse, "description": "未登录、会话失效或账号不可用"},
        403: {"model": ErrorResponse, "description": "需要管理员权限"},
        422: {"model": ErrorResponse, "description": "VALIDATION_ERROR；不回显输入"},
        503: {"model": ErrorResponse, "description": "OPS_DATA_UNAVAILABLE；台账尚未接入或暂不可用"},
    },
)


@contextmanager
def _safe_query() -> Iterator[None]:
    try:
        yield
    except OpsDataUnavailable as exc:
        raise AppError("OPS_DATA_UNAVAILABLE", "运行数据暂不可用，请稍后重试", 503) from exc


def get_ops_queries(db: Session = Depends(get_db)) -> OpsQueryService:
    """正式模型未注册时安全拒绝；测试可在依赖边界注入独立临时台账。"""
    with _safe_query():
        return OpsQueryService(db, registered_ops_table())


def _window(query: OpsFilters, now: datetime) -> OpsWindow:
    try:
        return query.window(now)
    except ValueError as exc:
        raise AppError("VALIDATION_ERROR", "请求字段格式错误或包含不允许的字段", 422) from exc


@router.get("/overview", response_model=OpsOverview, summary="查询运行概览")
def overview(
    query: Annotated[OpsFilters, Query()], response: Response,
    service: Annotated[OpsQueryService, Depends(get_ops_queries)],
) -> OpsOverview:
    """按 accepted_at 聚合已记录运行；最近运行最多 10 条，未知单独计数。"""
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    window = _window(query, now)
    with _safe_query():
        return service.overview(query, window, now)


@router.get("/runs", response_model=OpsRuns, summary="查询运行列表")
def runs(
    query: Annotated[OpsRunsQuery, Query()], response: Response,
    service: Annotated[OpsQueryService, Depends(get_ops_queries)],
) -> OpsRuns:
    """按 accepted_at、run_id 倒序排列，支持 limit/offset；不推断状态或补写记录。"""
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    window = _window(query, now)
    with _safe_query():
        return service.list_runs(query, window, now)


@router.get(
    "/runs/{run_id}", response_model=OpsRunDetail, summary="查询运行基本详情",
    responses={404: {"model": ErrorResponse, "description": "OPS_RUN_NOT_FOUND；运行记录不存在"}},
)
def run_detail(
    run_id: Annotated[OpsId, Path()], response: Response,
    service: Annotated[OpsQueryService, Depends(get_ops_queries)],
) -> OpsRunDetail:
    """只返回运行摘要及业务标识，不返回题目、对话、追踪正文或模型配置。"""
    response.headers["Cache-Control"] = "no-store"
    with _safe_query():
        result = service.get_run(run_id, datetime.now(timezone.utc))
    if result is None:
        raise AppError("OPS_RUN_NOT_FOUND", "运行记录不存在", 404)
    return result

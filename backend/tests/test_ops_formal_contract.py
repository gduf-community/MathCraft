"""正式 ORM 接入门槛；缺少甲模型时明确跳过，不用合成表冒充集成成功。"""
from datetime import datetime
from importlib import import_module
from importlib.util import find_spec
from types import ModuleType

import pytest
from sqlalchemy.orm import Session

from app.services.ops_queries import SAFE_ERROR_CODES, OpsQueryService, registered_ops_table


@pytest.fixture(scope="module")
def formal_contract() -> ModuleType:
    """仅加载实际交付的 app.models.ops_run，测试自身不复制、修补或声明模型。"""
    if find_spec("app.models.ops_run") is None:
        pytest.skip("甲正式 OpsRun 尚未提供；需在保留甲原始模型的隔离集成目录执行")
    return import_module("app.models.ops_run")


def test_formal_error_codes_are_exactly_allowlisted(formal_contract: ModuleType) -> None:
    """甲枚举变化必须显式复核，不自动扩展生产白名单。"""
    assert {member.value for member in formal_contract.RunErrorCode} == SAFE_ERROR_CODES


def test_formal_utc_type_and_registered_orm_are_query_compatible(
    formal_contract: ModuleType,
) -> None:
    """验证实际 UTCDateTime 和正式注册表；失败时不得运行后续迁移/查询集成验收。"""
    assert formal_contract.UTCDateTime().python_type is datetime, (
        "甲 UTCDateTime 必须显式声明 python_type 为 datetime；正式台账联调仍被阻塞"
    )
    table = formal_contract.OpsRun.__table__
    assert registered_ops_table() is table
    for name in ("accepted_at", "started_at", "finished_at", "last_observed_at"):
        assert table.c[name].type.python_type is datetime
    # 不绑定引擎、不建表、不执行 SQL；只验证正式 ORM 能通过生产查询服务的类型门槛。
    with Session() as db:
        OpsQueryService(db, table)

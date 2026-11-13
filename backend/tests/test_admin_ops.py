"""真实管理员鉴权 + 注入测试台账的 V2 HTTP 契约验证。"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, select, text

from app.api import admin_ops
from app.main import app
from app.models import User
from app.services.ops_queries import OpsDataUnavailable, OpsQueryService
from ops_fixtures import NOW, enum_ledger, ledger, run_row, seed
from test_admin import admin_headers

PATHS = ("/api/admin/ops/overview", "/api/admin/ops/runs", "/api/admin/ops/runs/run_fixture")
WINDOW = {"from": NOW.isoformat(), "to": (NOW + timedelta(seconds=1)).isoformat()}


@pytest.fixture
def admin(client, db):
    return admin_headers(client, db)


@pytest.fixture
def queries(client, ledger):
    """只替换台账读取依赖；应用鉴权、错误处理与序列化使用正式实现。"""
    service = OpsQueryService(*ledger)
    app.dependency_overrides[admin_ops.get_ops_queries] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(admin_ops.get_ops_queries, None)


@pytest.mark.parametrize("path", PATHS)
def test_all_routes_require_auth_before_obtaining_ledger(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("role", ["teacher", "student"])
def test_nonadmins_cannot_access_or_probe_ledger(client, auth, role, path):
    response = client.get(path, headers=auth(role, role))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", PATHS)
def test_missing_formal_model_is_503_not_empty_success(client, admin, monkeypatch, path):
    def unavailable():
        raise OpsDataUnavailable("synthetic internal integration detail")

    monkeypatch.setattr(admin_ops, "registered_ops_table", unavailable)
    response = client.get(path, headers=admin)
    assert response.status_code == 503
    assert response.json() == {"detail": {
        "code": "OPS_DATA_UNAVAILABLE", "message": "运行数据暂不可用，请稍后重试",
    }}
    assert response.headers["cache-control"] == "no-store"


def test_success_shapes_nulls_utc_counts_and_read_only_sql(client, admin, ledger, queries):
    seed(ledger, run_row(), run_row("run_complete", status="completed", delivered_count=2,
                                 requested_count=3, batch_id="batch_known"))
    db, table = ledger
    before = db.execute(select(table)).mappings().all()
    statements = []
    event.listen(db.connection(), "before_cursor_execute", lambda c, x, sql, p, ctx, many:
                 statements.append(sql))
    overview = client.get(PATHS[0], headers=admin, params=WINDOW)
    listing = client.get(PATHS[1], headers=admin, params={**WINDOW, "limit": 1})
    detail = client.get(PATHS[2], headers=admin)
    for response in (overview, listing, detail):
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["schema_version"] == "v2"
        assert response.json()["generated_at"].endswith("Z")
        assert "synthetic-private-body" not in response.text
        assert "execution_status" not in response.text
    summary = overview.json()
    assert set(summary) == {"schema_version", "generated_at", "window", "total_runs",
                            "status_counts", "recent_runs"}
    assert summary["total_runs"] == 2
    assert summary["status_counts"]["unknown"] == summary["status_counts"]["completed"] == 1
    assert listing.json()["page"] == {"limit": 1, "offset": 0, "has_more": True}
    assert detail.json()["run"]["requested_count"] is None
    assert detail.json()["run"]["finished_at"] is None
    assert detail.json()["run"]["last_observed_at"] is None
    assert all(statement.lstrip().split()[0].upper() in {"SELECT", "WITH"}
               for statement in statements)
    assert db.execute(select(table)).mappings().all() == before


def test_missing_run_is_safe_404_and_empty_query_is_200(client, admin, queries):
    response = client.get(PATHS[2], headers=admin)
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "OPS_RUN_NOT_FOUND", "message": "运行记录不存在"}
    assert client.get(PATHS[0], headers=admin).json()["total_runs"] == 0
    assert client.get(PATHS[1], headers=admin).json()["items"] == []


@pytest.mark.parametrize("params", [
    {"from": "synthetic-secret-invalid-date"}, {"from": "2026-11-13T12:00:00"},
    {"from": "9999-12-31T23:59:59Z"}, {**WINDOW, "from": "2026-11-14T00:00:00Z"},
    {"to": "0001-01-01T00:00:00Z"}, {"status": "cancelled"}, {"entrypoint": "chat"},
    {"owner_user_id": "u' OR 1=1"}, {"limit": 101}, {"offset": -1}, {"limit": "abc"},
    {"snapshot": "synthetic-secret-old-contract"},
])
def test_invalid_queries_use_safe_422(client, admin, queries, params):
    response = client.get(PATHS[1], headers=admin, params=params)
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": {
        "code": "VALIDATION_ERROR", "message": "请求字段格式错误或包含不允许的字段",
    }}
    assert "synthetic-secret" not in response.text


@pytest.mark.parametrize("mode", ["disabled", "role_changed", "token_revoked"])
def test_account_and_session_changes_are_honored(client, admin, queries, db, mode):
    user = db.query(User).filter(User.account == "admin").one()
    if mode == "disabled":
        user.status = "disabled"
    elif mode == "role_changed":
        user.role = "teacher"
    else:
        user.auth_version += 1
    db.commit()
    for path in PATHS:
        response = client.get(path, headers=admin)
        assert response.status_code in {401, 403}


@pytest.mark.parametrize("path", PATHS)
def test_sql_failure_is_masked_for_every_route(client, admin, queries, ledger, path):
    db, table = ledger
    table.drop(db.connection())
    response = client.get(path, headers=admin, params=WINDOW if path != PATHS[2] else None)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "OPS_DATA_UNAVAILABLE"
    assert "ops_runs" not in response.text and "SELECT" not in response.text


def test_basic_detail_hides_arbitrary_error_text_and_validation_details(
    client, admin, queries, ledger,
):
    seed(ledger, run_row(error_code="synthetic-password=private"))
    response = client.get(PATHS[2], headers=admin)
    assert response.status_code == 200
    assert response.json()["run"]["error_code"] == "UNKNOWN"
    assert "synthetic-password" not in response.text
    ledger[0].execute(ledger[1].update().values(status="synthetic-invalid-status"))
    ledger[0].commit()
    response = client.get(PATHS[2], headers=admin)
    assert response.status_code == 503
    assert "synthetic-invalid-status" not in response.text


@pytest.mark.parametrize("path", PATHS[:2])
@pytest.mark.parametrize("params", [
    {"to": "0001-01-01T00:00:00+01:00"},
    {"to": "9999-12-31T23:59:59-01:00"},
    {"from": "0001-01-01T00:00:00+01:00", "to": "0001-01-01T01:00:00Z"},
    {"from": "9999-12-31T23:59:59-01:00"},
    {"to": "0001-01-01T00:00:00Z"},  # 默认向前 24 小时超出年份下界
    {"from": "0000-01-01T00:00:00Z"},
    {"to": "10000-01-01T00:00:00Z"},
    {"to": "2026-11-13T12:00:00+24:00"},
])
def test_time_parse_conversion_and_default_window_fail_with_safe_422(
    client, admin, queries, path, params,
):
    response = client.get(path, headers=admin, params=params)
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": {
        "code": "VALIDATION_ERROR", "message": "请求字段格式错误或包含不允许的字段",
    }}


@pytest.mark.parametrize("path", PATHS[:2])
@pytest.mark.parametrize("start,end,expected_start,expected_end", [
    ("0001-01-01T01:00:00+01:00", "0001-01-01T02:00:00+01:00",
     "0001-01-01T00:00:00Z", "0001-01-01T01:00:00Z"),
    ("9999-12-31T22:59:58-01:00", "9999-12-31T22:59:59.999999-01:00",
     "9999-12-31T23:59:58Z", "9999-12-31T23:59:59.999999Z"),
    ("2026-11-13T12:00:00Z", "2026-11-13T12:00:01Z",
     "2026-11-13T12:00:00Z", "2026-11-13T12:00:01Z"),
    ("2026-11-13T20:00:00.123+08:00", "2026-11-13T20:00:01.123+08:00",
     "2026-11-13T12:00:00.123Z", "2026-11-13T12:00:01.123Z"),
    ("2026-11-13T04:30:00.123456789-07:30", "2026-11-13T04:30:01.123456789-07:30",
     "2026-11-13T12:00:00.123456Z", "2026-11-13T12:00:01.123456Z"),
    ("2026-11-13t12:00:00z", "2026-11-13t12:00:01z",
     "2026-11-13T12:00:00Z", "2026-11-13T12:00:01Z"),
])
def test_valid_iso_times_keep_utc_windows(
    client, admin, queries, path, start, end, expected_start, expected_end,
):
    response = client.get(path, headers=admin, params={"from": start, "to": end})
    assert response.status_code == 200, response.text
    window = response.json()["window"]
    assert datetime.fromisoformat(window["from"]) == datetime.fromisoformat(expected_start)
    assert datetime.fromisoformat(window["to"]) == datetime.fromisoformat(expected_end)
    assert window["time_basis"] == "accepted_at"


@pytest.mark.parametrize("path", PATHS[:2])
@pytest.mark.parametrize("field", ["from", "to"])
def test_http_query_times_reject_numeric_and_unix_inputs(client, admin, queries, path, field):
    for value in ("0", "1", "-1", "1.25", "1e3", "1700000000", "1700000000000"):
        response = client.get(path, headers=admin, params={field: value})
        assert response.status_code == 422, (field, value, response.text)
        assert response.json() == {"detail": {
            "code": "VALIDATION_ERROR", "message": "请求字段格式错误或包含不允许的字段",
        }}


@pytest.mark.parametrize("path", PATHS)
def test_enum_decode_failure_uses_safe_503(
    client, admin, enum_ledger, monkeypatch, path,
):
    db, table = enum_ledger
    seed(enum_ledger, run_row())
    db.execute(text("UPDATE ops_runs SET status = :value"),
               {"value": "synthetic-invalid-enum-private-value"})
    db.commit()
    service = OpsQueryService(db, table)
    monkeypatch.setitem(app.dependency_overrides, admin_ops.get_ops_queries, lambda: service)
    response = client.get(path, headers=admin, params=WINDOW if path != PATHS[2] else None)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": {
        "code": "OPS_DATA_UNAVAILABLE", "message": "运行数据暂不可用，请稍后重试",
    }}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("code,expected", [
    # 与甲 cdcdf212 的有限枚举逐项对照，不能从被测白名单生成预期。
    ("NEED_CONFIRM", "NEED_CONFIRM"),
    ("MODEL_ERROR", "MODEL_ERROR"),
    ("RETRIEVAL_ERROR", "RETRIEVAL_ERROR"),
    ("GENERATION_ERROR", "GENERATION_ERROR"),
    ("NO_PERSISTABLE_QUESTIONS", "NO_PERSISTABLE_QUESTIONS"),
    ("PERSISTENCE_ERROR", "PERSISTENCE_ERROR"),
    ("TASK_SUBMISSION_ERROR", "TASK_SUBMISSION_ERROR"),
    ("EXECUTION_ERROR", "EXECUTION_ERROR"),
    ("USER_CANCELED", "USER_CANCELED"),
    ("EXECUTION_INTERRUPTED", "EXECUTION_INTERRUPTED"),
    ("OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"),
    (None, None), ("UNKNOWN", "UNKNOWN"),
    ("", "UNKNOWN"), ("PERSIST_FAILED", "UNKNOWN"),
    ("MODEL_ERROR\nsynthetic-private-detail", "UNKNOWN"),
    ("SELECT synthetic_private FROM ops_runs", "UNKNOWN"),
    ("synthetic model reply", "UNKNOWN"),
    ("synthetic password=private", "UNKNOWN"),
])
def test_confirmed_error_codes_and_untrusted_text_on_all_routes(
    client, admin, ledger, queries, code, expected,
):
    """三种响应投影保留有限安全分类；正文、旧分类和自由文本均不透传。"""
    seed(ledger, run_row(error_code=code))
    overview = client.get(PATHS[0], headers=admin, params=WINDOW)
    listing = client.get(PATHS[1], headers=admin, params=WINDOW)
    detail = client.get(PATHS[2], headers=admin)
    assert overview.status_code == listing.status_code == detail.status_code == 200
    rows = (overview.json()["recent_runs"][0], listing.json()["items"][0], detail.json()["run"])
    assert all(row["error_code"] == expected for row in rows)
    if code and code != expected:
        assert all(code not in response.text for response in (overview, listing, detail))

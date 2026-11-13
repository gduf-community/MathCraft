"""V2 SQL 聚合、过滤、分页、未知值和故障边界的独立台账验证。"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, String, Table, event, select, text
from sqlalchemy.orm import registry

from app.schemas.ops import OpsFilters, OpsRunsQuery
from app.services import ops_queries
from app.services.ops_queries import OpsDataUnavailable, OpsQueryService
from ops_fixtures import NOW, enum_ledger, ledger, run_row, seed


def test_window_defaults_and_timezone_are_unambiguous():
    window = OpsFilters().window(NOW)
    assert window.from_ == NOW - timedelta(days=1)
    assert window.to == NOW
    assert window.model_dump(mode="json", by_alias=True)["to"].endswith("Z")
    past = OpsFilters.model_validate({"to": "2026-11-12T20:00:00+08:00"}).window(NOW)
    assert past.to == NOW - timedelta(days=1)
    assert past.from_ == NOW - timedelta(days=2)


@pytest.mark.parametrize("params", [
    {"from": "2026-11-13T12:00:00"}, {"to": "not-a-date"},
    {"from": NOW.isoformat(), "to": NOW.isoformat()},
    {"from": (NOW + timedelta(seconds=1)).isoformat(), "to": NOW.isoformat()},
    {"status": "cancelled"}, {"status": "success"}, {"entrypoint": "chat"},
    {"owner_user_id": ""}, {"owner_user_id": "u' OR 1=1"}, {"owner_user_id": "a" * 129},
    {"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 2**63},
    {"cursor": "legacy"},
])
def test_invalid_filters_and_legacy_fields_are_rejected(params):
    with pytest.raises(ValidationError):
        OpsRunsQuery.model_validate(params)


def test_future_start_without_end_is_invalid():
    with pytest.raises(ValueError):
        OpsFilters.model_validate({"from": (NOW + timedelta(seconds=1)).isoformat()}).window(NOW)


def test_empty_ledger_is_known_empty_not_unavailable(ledger):
    service = OpsQueryService(*ledger)
    query = OpsRunsQuery()
    window = query.window(NOW)
    overview = service.overview(query, window, NOW)
    assert overview.total_runs == 0
    assert set(overview.status_counts.model_dump().values()) == {0}
    assert overview.recent_runs == []
    listing = service.list_runs(query, window, NOW)
    assert listing.items == [] and listing.page.has_more is False
    assert service.get_run("missing", NOW) is None


def test_overview_counts_all_six_states_and_limits_recent_with_one_select(ledger):
    states = ("accepted", "running", "completed", "failed", "canceled", "unknown")
    seed(ledger, *(run_row(f"run_{i:02}", status=states[i % 6]) for i in range(18)))
    service = OpsQueryService(*ledger)
    query = OpsFilters.model_validate({
        "from": NOW.isoformat(), "to": (NOW + timedelta(seconds=1)).isoformat(),
    })
    statements = []
    connection = ledger[0].connection()
    event.listen(connection, "before_cursor_execute", lambda c, x, sql, p, ctx, many:
                 statements.append(sql))
    result = service.overview(query, query.window(NOW), NOW)
    assert result.total_runs == 18
    assert set(result.status_counts.model_dump().values()) == {3}
    assert [item.run_id for item in result.recent_runs] == [f"run_{i:02}" for i in range(17, 7, -1)]
    assert len(statements) == 1


def test_half_open_time_window_and_stable_tie_pagination(ledger):
    seed(ledger, run_row("before", accepted_at=NOW - timedelta(microseconds=1)),
         run_row("a"), run_row("b"), run_row("c"),
         run_row("after", accepted_at=NOW + timedelta(seconds=1)))
    service = OpsQueryService(*ledger)
    # +08:00 输入必须归一化成 UTC 后进行 SQL 比较。
    query = OpsRunsQuery.model_validate({
        "from": "2026-11-13T20:00:00+08:00", "to": "2026-11-13T20:00:01+08:00", "limit": 2,
    })
    first = service.list_runs(query, query.window(NOW), NOW)
    second_query = query.model_copy(update={"offset": 2})
    second = service.list_runs(second_query, query.window(NOW), NOW)
    assert [r.run_id for r in first.items] == ["c", "b"]
    assert first.page.has_more
    assert [r.run_id for r in second.items] == ["a"]
    assert not second.page.has_more
    assert service.overview(query, query.window(NOW), NOW).total_runs == 3
    assert service.get_run("before", NOW) is not None  # 详情没有默认 24 小时限制


@pytest.mark.parametrize(("field", "value", "other"), [
    ("owner_user_id", "u_two", "u_one"), ("entrypoint", "conversation", "parameterized"),
    ("status", "canceled", "completed"), ("session_id", "session_two", "session_one"),
    ("task_id", "task_two", "task_one"), ("batch_id", "batch_two", "batch_one"),
])
def test_each_filter_applies_to_both_aggregation_and_list(ledger, field, value, other):
    seed(ledger, run_row("match", **{field: value}), run_row("exclude", **{field: other}))
    service = OpsQueryService(*ledger)
    query = OpsRunsQuery.model_validate({field: value, "from": NOW.isoformat(),
                                        "to": (NOW + timedelta(seconds=1)).isoformat()})
    window = query.window(NOW)
    assert [r.run_id for r in service.list_runs(query, window, NOW).items] == ["match"]
    result = service.overview(query, window, NOW)
    assert result.total_runs == 1
    assert [r.run_id for r in result.recent_runs] == ["match"]


def test_combined_filters_are_and_conditions(ledger):
    seed(ledger, run_row("both", owner_user_id="u_one", status="completed"),
         run_row("owner_only", owner_user_id="u_one", status="failed"),
         run_row("status_only", owner_user_id="u_two", status="completed"))
    query = OpsRunsQuery.model_validate({
        "owner_user_id": "u_one", "status": "completed", "from": NOW.isoformat(),
        "to": (NOW + timedelta(seconds=1)).isoformat(),
    })
    service = OpsQueryService(*ledger)
    assert [r.run_id for r in service.list_runs(query, query.window(NOW), NOW).items] == ["both"]


def test_projection_preserves_null_zero_unknown_and_does_not_modify_ledger(ledger):
    seed(ledger, run_row(delivered_count=0))
    db, table = ledger
    before = db.execute(select(table)).mappings().all()
    service = OpsQueryService(*ledger)
    result = service.get_run("run_fixture", NOW)
    assert result is not None
    payload = result.model_dump(mode="json")["run"]
    assert payload["status"] == "unknown"
    assert payload["delivered_count"] == 0
    assert payload["requested_count"] is None
    assert payload["finished_at"] is None and payload["last_observed_at"] is None
    assert payload["accepted_at"].endswith("Z")
    assert "private_body" not in payload
    assert "synthetic-private-body" not in str(payload)
    after = db.execute(select(table)).mappings().all()
    assert before == after
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("code,expected", [
    (None, None), ("PERSIST_FAILED", "UNKNOWN"),
    ("SYNTHETIC_SECRET_VALUE", "UNKNOWN"), ("synthetic password=do-not-return", "UNKNOWN"),
])
def test_error_codes_never_echo_arbitrary_recorded_strings(ledger, code, expected):
    seed(ledger, run_row(error_code=code))
    result = OpsQueryService(*ledger).get_run("run_fixture", NOW)
    assert result is not None and result.run.error_code == expected


@pytest.mark.parametrize("changes", [
    {"status": "not-a-valid-status"}, {"accepted_at": None},
    {"entrypoint": "old-sdk"}, {"delivered_count": -1}, {"requested_count": 0},
])
def test_incompatible_rows_are_unavailable_not_invented_facts(ledger, changes):
    seed(ledger, run_row(**changes))
    with pytest.raises(OpsDataUnavailable):
        OpsQueryService(*ledger).get_run("run_fixture", NOW)


def test_unrecognized_status_outside_recent_ten_still_breaks_overview(ledger):
    seed(ledger, run_row("old_bad", status="invalid", accepted_at=NOW - timedelta(seconds=1)),
         *(run_row(f"run_{i:02}") for i in range(11)))
    query = OpsFilters.model_validate({
        "from": (NOW - timedelta(hours=1)).isoformat(),
        "to": (NOW + timedelta(seconds=1)).isoformat(),
    })
    with pytest.raises(OpsDataUnavailable):
        OpsQueryService(*ledger).overview(query, query.window(NOW), NOW)


def test_unmigrated_table_and_invalid_date_are_safe_unavailability(ledger):
    db, table = ledger
    seed(ledger, run_row())
    db.execute(text("UPDATE ops_runs SET accepted_at = 'synthetic-invalid-date'"))
    with pytest.raises(OpsDataUnavailable):
        OpsQueryService(*ledger).get_run("run_fixture", NOW)
    db.rollback()
    table.drop(db.connection())
    with pytest.raises(OpsDataUnavailable):
        OpsQueryService(*ledger).get_run("run_fixture", NOW)


def test_contract_rejects_missing_columns_and_nonunique_run_ids(ledger):
    db, table = ledger
    with pytest.raises(OpsDataUnavailable):
        OpsQueryService(db, Table("incompatible", MetaData(), Column("run_id", String)))
    clone = table.to_metadata(MetaData(), name="without_primary_key")
    clone.primary_key = type(table.primary_key)()
    with pytest.raises(OpsDataUnavailable):
        OpsQueryService(db, clone)


@pytest.mark.parametrize("field", ["accepted_at", "last_observed_at", "requested_count"])
def test_incompatible_column_types_do_not_silently_return_false_empty_results(ledger, field):
    db, table = ledger
    incompatible = table.to_metadata(MetaData())
    incompatible.c[field].type = String()
    with pytest.raises(OpsDataUnavailable):
        OpsQueryService(db, incompatible)


def test_registry_lookup_reuses_only_a_registered_formal_table(ledger, monkeypatch):
    isolated_registry = registry()
    monkeypatch.setattr(ops_queries, "Base", SimpleNamespace(registry=isolated_registry))
    with pytest.raises(OpsDataUnavailable):
        ops_queries.registered_ops_table()

    class TestOnlyRun:
        """测试映射不进入公共应用模型 registry。"""

    isolated_registry.map_imperatively(TestOnlyRun, ledger[1])
    try:
        assert ops_queries.registered_ops_table() is ledger[1]
    finally:
        isolated_registry.dispose()


@pytest.mark.parametrize("field", ["from", "to"])
@pytest.mark.parametrize("value", [1, 1.25, True, NOW])
def test_query_times_reject_non_string_objects(field, value):
    with pytest.raises(ValidationError):
        OpsFilters.model_validate({field: value})


def test_valid_enum_results_keep_all_six_states(enum_ledger):
    states = ("accepted", "running", "completed", "failed", "canceled", "unknown")
    seed(enum_ledger, *(run_row(f"enum_{status}", status=status) for status in states))
    service = OpsQueryService(*enum_ledger)
    query = OpsRunsQuery.model_validate({
        "from": NOW.isoformat(), "to": (NOW + timedelta(seconds=1)).isoformat(),
    })
    overview = service.overview(query, query.window(NOW), NOW)
    assert overview.total_runs == 6
    assert set(overview.status_counts.model_dump().values()) == {1}
    assert {
        run.status for run in service.list_runs(query, query.window(NOW), NOW).items
    } == set(states)
    detail = service.get_run("enum_unknown", NOW)
    assert detail is not None and detail.run.status == "unknown"


def test_non_read_lookup_errors_are_not_masked(ledger, monkeypatch):
    seed(ledger, run_row())
    service = OpsQueryService(*ledger)

    def broken_projection(_row):
        raise KeyError("synthetic programming error")

    monkeypatch.setattr(service, "_run", broken_projection)
    with pytest.raises(KeyError, match="synthetic programming error"):
        service.get_run("run_fixture", NOW)

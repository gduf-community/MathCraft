"""Actual A generation paths -> migrated ledger -> unmodified B admin queries."""
# ruff: noqa: E402 -- Optional A integration must skip before importing its dependencies.
from importlib.util import find_spec

import pytest

if find_spec("app.models.ops_run") is None:
    pytest.skip("A formal ledger is not integrated into this checkout", allow_module_level=True)

from datetime import timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import BackgroundTasks
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import conftest
from app.db import SessionLocal, engine
from app.models import OpsRun
from app.services.rag import question_gen, chat_flow
from test_admin import admin_headers
from test_generation_runs import resources, body, post_chat, records


@pytest.fixture(autouse=True)
def migrated_database(monkeypatch):
    """Replace only fixture schema setup; production sessions and writers remain real."""
    def clear_database():
        # 新增的主线表使旧 SQLite 数据库的删表顺序受外键约束；仅在测试清理阶段关闭。
        with engine.connect() as connection:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.commit()
            try:
                virtual_tables = connection.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND UPPER(sql) LIKE 'CREATE VIRTUAL TABLE%'"
                )).scalars().all()
                for name in virtual_tables:
                    quoted_name = name.replace('"', '""')
                    connection.execute(text(f'DROP TABLE IF EXISTS "{quoted_name}"'))
                table_names = [
                    name for name in inspect(connection).get_table_names()
                    if name != "sqlite_sequence"
                ]
                for name in sorted(table_names, reverse=True):
                    quoted_name = name.replace('"', '""')
                    connection.execute(text(f'DROP TABLE IF EXISTS "{quoted_name}"'))
                connection.commit()
            finally:
                connection.rollback()
                connection.execute(text("PRAGMA foreign_keys=ON"))
                connection.commit()
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1

    def reset():
        clear_database()
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        command.upgrade(config, "i4d5e6f7a890")
        command.upgrade(config, "head")
    monkeypatch.setattr(conftest, "_reset_database", reset)
    yield
    # 真实迁移包含 ORM metadata 不认识的表，不能留给后续公共夹具清理。
    clear_database()


def query_actual(client, headers, expected_status, expected_id=None):
    row, = records()
    assert row.status == expected_status
    if expected_id is not None:
        assert row.run_id == expected_id
    with SessionLocal() as db:
        before = db.execute(select(OpsRun.__table__)).all()
    params = {"from": (row.accepted_at - timedelta(seconds=1)).isoformat(),
              "to": (row.accepted_at + timedelta(seconds=1)).isoformat(),
              "owner_user_id": row.owner_user_id, "entrypoint": row.entrypoint}
    detail = client.get(f"/api/admin/ops/runs/{row.run_id}", headers=headers)
    listing = client.get("/api/admin/ops/runs", params=params, headers=headers)
    overview = client.get("/api/admin/ops/overview", params=params, headers=headers)
    assert detail.status_code == listing.status_code == overview.status_code == 200
    projected = detail.json()["run"]
    assert projected["status"] == expected_status
    assert projected["run_id"] == row.run_id
    for name in ("batch_id", "task_id", "session_id", "error_code", "delivered_count"):
        assert projected[name] == getattr(row, name)
    assert listing.json()["items"] == overview.json()["recent_runs"] == [projected]
    assert overview.json()["total_runs"] == 1
    assert overview.json()["status_counts"][expected_status] == 1
    with SessionLocal() as db:
        assert db.execute(select(OpsRun.__table__)).all() == before
    return row


@pytest.mark.parametrize("path", ["chat", "/api/generate", "/api/generate/start"])
def test_actual_paths_publish_completed_runs_to_admin_queries(
    client, teacher, resources, db, monkeypatch, path,
):
    headers = admin_headers(client, db)
    original = chat_flow.generate_questions if path == "chat" else question_gen.generate_questions
    seen = []

    def generate(*args, **kwargs):
        seen.append(query_actual(client, headers, "running").run_id)
        return original(*args, **kwargs)

    monkeypatch.setattr(chat_flow if path == "chat" else question_gen, "generate_questions", generate)
    queued = []
    if path.endswith("start"):
        monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, fn, *a, **kw:
                            queued.append((fn, a, kw)))
    response = (post_chat(client, teacher, resources) if path == "chat" else
                client.post(path, headers=teacher, json=body(resources)))
    assert response.status_code in (200, 202), response.text
    if queued:
        accepted = query_actual(client, headers, "accepted")
        assert accepted.task_id == response.json()["task_id"]
        fn, args, kwargs = queued[0]
        assert kwargs["run_id"] == accepted.run_id
        fn(*args, **kwargs)
    assert len(seen) == 1
    completed = query_actual(client, headers, "completed", seen[0])
    assert completed.requested_count == completed.delivered_count == 2
    assert completed.batch_id is not None
    assert completed.session_id == (resources["session_id"] if path == "chat" else None)
    assert completed.accepted_at <= completed.started_at <= completed.finished_at


@pytest.mark.parametrize("path", ["chat", "/api/generate", "/api/generate/start"])
def test_actual_failure_is_queryable_without_exception_body(
    client, teacher, resources, db, monkeypatch, path,
):
    headers = admin_headers(client, db)

    def reject(*args, **kwargs):
        raise ValueError("synthetic-private-generation-fault")

    monkeypatch.setattr(question_gen, "generate_questions", reject)
    monkeypatch.setattr(chat_flow, "generate_questions", reject)
    try:
        response = (post_chat(client, teacher, resources) if path == "chat" else
                    client.post(path, headers=teacher, json=body(resources)))
        assert "synthetic-private-generation-fault" not in response.text
    except ValueError as exc:
        assert str(exc) == "synthetic-private-generation-fault"
    row = query_actual(client, headers, "failed")
    assert row.error_code == "GENERATION_ERROR"
    assert row.delivered_count == 0 and row.batch_id is None


def test_actual_chat_cancel_remains_running_until_ack_then_is_queryable(
    client, teacher, resources, db, monkeypatch,
):
    headers = admin_headers(client, db)
    original = chat_flow.generate_questions

    def generate(*args, **kwargs):
        response = client.post(
            f"/api/chat/sessions/{resources['session_id']}/cancel", headers=teacher,
        )
        assert response.status_code == 202
        query_actual(client, headers, "running")
        return original(*args, **kwargs)

    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    assert post_chat(client, teacher, resources).status_code == 200
    row = query_actual(client, headers, "canceled")
    assert row.error_code == "USER_CANCELED" and row.delivered_count == 0


def test_uncertain_business_commit_is_queryable_as_unknown(
    client, teacher, resources, db, monkeypatch,
):
    from app.services.generation_lifecycle import GenerationRun

    headers = admin_headers(client, db)
    complete = GenerationRun.complete_in_transaction
    commit = Session.commit

    def prepare(self, session, batch_id):
        complete(self, session, batch_id)
        session.info["synthetic_uncertain_commit"] = True

    def uncertain_commit(session):
        if session.info.pop("synthetic_uncertain_commit", False):
            raise SQLAlchemyError("synthetic-private-commit-fault")
        return commit(session)

    monkeypatch.setattr(GenerationRun, "complete_in_transaction", prepare)
    monkeypatch.setattr(Session, "commit", uncertain_commit)
    response = client.post("/api/generate", headers=teacher, json=body(resources))
    assert response.status_code == 503
    assert "synthetic-private-commit-fault" not in response.text
    row = query_actual(client, headers, "unknown")
    assert row.error_code == "OUTCOME_UNKNOWN"
    assert row.finished_at is row.delivered_count is row.batch_id is None

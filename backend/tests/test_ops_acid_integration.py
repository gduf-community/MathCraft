"""持久出题任务与运维台账共享运行事实和事务边界。"""
from datetime import datetime, timedelta, timezone
import logging
from types import SimpleNamespace

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api import chat
from app.db import SessionLocal, engine
from app.main import app
from app.models import ChatSession, GenerationBatch, OpsRun, Question
from app.models.generation_task import GenerationTask
from app.models.ops_run import RunEntrypoint, RunErrorCode
from app.schemas.api import GenerateStartBody
from app.services import generation
from app.services.generation_lifecycle import GenerationRun
from app.services.ops_runs import RunLedger
from test_admin import admin_headers
from test_generation_runs import body, resources


def test_task_and_ledger_are_accepted_and_completed_together(client, teacher, resources, monkeypatch):
    queued = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda _self, function, *args, **kwargs:
                        queued.append((function, args, kwargs)))

    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    assert response.status_code == 202
    with SessionLocal() as db:
        task = db.get(GenerationTask, response.json()["task_id"])
        run = db.get(OpsRun, task.run_id)
        assert task.status == "queued"
        assert run.status == "accepted" and run.task_id == task.id
        assert queued[0][2]["run_id"] == task.run_id
        run_id = task.run_id

    function, args, kwargs = queued[0]
    function(*args, **kwargs)
    with SessionLocal() as db:
        task = db.get(GenerationTask, response.json()["task_id"])
        run = db.get(OpsRun, run_id)
        assert task.status == "done" and run.status == "completed"
        assert task.batch_id == run.batch_id
        assert db.scalar(select(func.count()).select_from(Question)) == run.delivered_count == 2


def test_failed_ledger_acceptance_rolls_back_the_task(client, teacher, resources, monkeypatch):
    accept = RunLedger.accept

    def reject_after_flush(self, **kwargs):
        accept(self, **kwargs)
        raise SQLAlchemyError("synthetic acceptance failure")

    monkeypatch.setattr(RunLedger, "accept", reject_after_flush)
    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    assert response.status_code == 503
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GenerationTask)) == 0
        assert db.scalar(select(func.count()).select_from(OpsRun)) == 0


def test_batch_and_ledger_completion_roll_back_with_task(client, teacher, resources, monkeypatch):
    complete = GenerationRun.complete_in_transaction

    def reject_after_flush(self, db, batch_id):
        complete(self, db, batch_id)
        raise SQLAlchemyError("synthetic transaction failure")

    monkeypatch.setattr(GenerationRun, "complete_in_transaction", reject_after_flush)
    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    assert response.status_code == 202
    with SessionLocal() as db:
        task = db.get(GenerationTask, response.json()["task_id"])
        run = db.get(OpsRun, task.run_id)
        assert task.status == "failed" and run.status == "failed"
        assert run.error_code == "PERSISTENCE_ERROR" and run.batch_id is None
        assert db.scalar(select(func.count()).select_from(GenerationBatch)) == 0
        assert db.scalar(select(func.count()).select_from(Question)) == 0


@pytest.mark.parametrize(
    "structure", ["missing_table", "missing_column", "incompatible_type", "short_column"],
)
def test_restart_recovers_tasks_and_chat_when_ledger_structure_is_unavailable(
    client, teacher, resources, monkeypatch, caplog, structure,
):
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *_args, **_kwargs: None)
    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    with SessionLocal.begin() as db:
        task_run_id = db.get(GenerationTask, task_id).run_id
        session = db.get(ChatSession, resources["session_id"])
        session.run_id = "synthetic-private-run-id"
        session.run_status = "running"

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ops_runs"))
        if structure != "missing_table":
            suffix = ", last_observed_at INTEGER" if structure == "incompatible_type" else ""
            if structure == "short_column":
                suffix = ", last_observed_at DATETIME"
            error_type = "VARCHAR(8)" if structure == "short_column" else "VARCHAR(32)"
            connection.execute(text(
                "CREATE TABLE ops_runs (run_id VARCHAR(40) PRIMARY KEY, "
                f"entrypoint VARCHAR(16), status VARCHAR(16), error_code {error_type}{suffix})"
            ))
            connection.execute(text(
                "INSERT INTO ops_runs (run_id, status) VALUES (:run_id, 'accepted')"
            ), {"run_id": task_run_id})

    with caplog.at_level(logging.WARNING, logger="app.generation"):
        generation.recover_interrupted_generation()

    with SessionLocal() as db:
        assert db.get(GenerationTask, task_id).status == "interrupted"
        assert db.get(ChatSession, resources["session_id"]).run_status == "interrupted"
    with engine.connect() as connection:
        assert inspect(connection).has_table("ops_runs") == (structure != "missing_table")
        if structure != "missing_table":
            assert connection.execute(text("SELECT run_id, status FROM ops_runs")).all() == [
                (task_run_id, "accepted")
            ]
    warnings = [record for record in caplog.records if record.name == "app.generation"]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert warnings[0].exc_info is None
    assert task_run_id not in warnings[0].getMessage()
    assert "synthetic-private-run-id" not in warnings[0].getMessage()


def test_restart_propagates_ledger_write_failure_and_rolls_back_business_recovery(
    client, teacher, resources, monkeypatch,
):
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *_args, **_kwargs: None)
    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    with SessionLocal.begin() as db:
        run_id = db.get(GenerationTask, task_id).run_id
        session = db.get(ChatSession, resources["session_id"])
        session.run_id = "synthetic-chat-run"
        session.run_status = "running"
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TRIGGER reject_ops_recovery BEFORE UPDATE ON ops_runs "
            "BEGIN SELECT RAISE(ABORT, 'synthetic-ledger-write-failure'); END"
        ))
    try:
        with pytest.raises(IntegrityError, match="synthetic-ledger-write-failure"):
            generation.recover_interrupted_generation()
        with SessionLocal() as db:
            assert db.get(GenerationTask, task_id).status == "queued"
            assert db.get(ChatSession, resources["session_id"]).run_status == "running"
            assert db.get(OpsRun, run_id).status == "accepted"
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TRIGGER reject_ops_recovery"))


@pytest.mark.parametrize("structure", ["missing_table", "missing_column"])
def test_startup_recovers_business_and_admin_queries_report_unavailable_ledger(
    client, teacher, resources, db, structure,
):
    headers = admin_headers(client, db)
    task_id = "task_synthetic_startup"
    with SessionLocal.begin() as session:
        session.add(GenerationTask(
            id=task_id, user_id=resources["owner"], bank_id=resources["bank_id"],
            document_id=resources["document_id"], run_id="run_synthetic_startup",
            params_json="{}",
        ))
        chat_session = session.get(ChatSession, resources["session_id"])
        chat_session.run_id = "run_synthetic_chat"
        chat_session.run_status = "running"
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ops_runs"))
        if structure == "missing_column":
            connection.execute(text("CREATE TABLE ops_runs (run_id VARCHAR(40) PRIMARY KEY)"))

    with TestClient(app) as restarted:
        response = restarted.get("/api/admin/ops/overview", headers=headers)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "OPS_DATA_UNAVAILABLE"
        with SessionLocal() as session:
            assert session.get(GenerationTask, task_id).status == "interrupted"
            assert session.get(ChatSession, resources["session_id"]).run_status == "interrupted"


def test_restart_marks_linked_task_ledger_unknown(client, teacher, resources, monkeypatch):
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *_args, **_kwargs: None)
    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    assert response.status_code == 202
    unrelated_id = RunLedger().accept(
        entrypoint=RunEntrypoint.PARAMETERIZED, owner_user_id=resources["owner"],
        bank_id=resources["bank_id"], document_id=resources["document_id"], requested_count=1,
    )

    generation.recover_interrupted_generation()
    with SessionLocal() as db:
        task = db.get(GenerationTask, response.json()["task_id"])
        run = db.get(OpsRun, task.run_id)
        assert task.status == "interrupted"
        assert run.status == "unknown" and run.error_code == "EXECUTION_INTERRUPTED"
        assert db.get(OpsRun, unrelated_id).status == "accepted"


@pytest.mark.parametrize(
    ("previous_offset", "expected_offset"),
    [(timedelta(minutes=-5), timedelta()), (timedelta(minutes=5), timedelta(minutes=5))],
    ids=["older_observation", "future_observation"],
)
def test_restart_never_moves_ledger_observation_backwards(
    client, teacher, resources, monkeypatch, previous_offset, expected_offset,
):
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *_args, **_kwargs: None)
    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    assert response.status_code == 202
    now = datetime(2200, 1, 1, tzinfo=timezone.utc)
    with SessionLocal.begin() as db:
        task = db.get(GenerationTask, response.json()["task_id"])
        run_id = task.run_id
        run = db.get(OpsRun, run_id)
        run.last_observed_at = now + previous_offset
        if previous_offset > timedelta():
            run.accepted_at = run.last_observed_at
    monkeypatch.setattr(generation, "utcnow", lambda: now)

    generation.recover_interrupted_generation()

    with SessionLocal() as db:
        run = db.get(OpsRun, run_id)
        assert run.status == "unknown" and run.error_code == "EXECUTION_INTERRUPTED"
        assert run.last_observed_at == now + expected_offset
        assert db.get(GenerationTask, response.json()["task_id"]).status == "interrupted"


def test_restart_reconciles_interrupted_chat_after_ledger_upgrade(client, teacher, resources):
    second = client.post("/api/chat/sessions", headers=teacher, json={
        "bank_id": resources["bank_id"], "document_id": resources["document_id"],
    })
    assert second.status_code == 201
    session_ids = (resources["session_id"], second.json()["session_id"])
    runs = []
    for session_id in session_ids:
        with SessionLocal() as db:
            run_id = chat._begin_run(db, session_id, resources["owner"]).run_id
        run = GenerationRun(
            RunEntrypoint.CONVERSATION, resources["owner"], resources["bank_id"],
            resources["document_id"], session_id=session_id, run_id=run_id,
        )
        run.begin(generation.build_params(GenerateStartBody(**body(resources))))
        runs.append(run)
    runs[1].fail(RunErrorCode.EXECUTION_ERROR)

    # 暂存正式表，构造保有旧数据但缺列的台账；测试结束前恢复原表。
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE ops_runs RENAME TO saved_ops_runs"))
        connection.execute(text(
            "CREATE TABLE ops_runs (run_id VARCHAR(40) PRIMARY KEY, "
            "status VARCHAR(16), error_code VARCHAR(32))"
        ))
        connection.execute(text(
            "INSERT INTO ops_runs SELECT run_id, status, error_code FROM saved_ops_runs"
        ))
    try:
        generation.recover_interrupted_generation()
        with SessionLocal() as db:
            for session_id, run in zip(session_ids, runs):
                session = db.get(ChatSession, session_id)
                assert session.run_status == "interrupted" and session.run_id == run.run_id
        with engine.connect() as connection:
            statuses = dict(connection.execute(text("SELECT run_id, status FROM ops_runs")).all())
            assert statuses == {runs[0].run_id: "running", runs[1].run_id: "failed"}
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE ops_runs"))
            connection.execute(text("ALTER TABLE saved_ops_runs RENAME TO ops_runs"))

    generation.recover_interrupted_generation()
    with SessionLocal() as db:
        pending = db.get(OpsRun, runs[0].run_id)
        finished = db.get(OpsRun, runs[1].run_id)
        assert pending.status == "unknown" and pending.error_code == "EXECUTION_INTERRUPTED"
        assert finished.status == "failed" and finished.error_code == "EXECUTION_ERROR"
        for session_id in session_ids:
            assert db.get(ChatSession, session_id).run_status == "interrupted"


@pytest.mark.parametrize("association", ["overwritten", "deleted"])
def test_restart_reconciles_chat_after_ledger_upgrade_loses_session_link(
    client, teacher, resources, monkeypatch, association,
):
    session_id = resources["session_id"]
    with SessionLocal() as db:
        run_id = chat._begin_run(db, session_id, resources["owner"]).run_id
    run = GenerationRun(
        RunEntrypoint.CONVERSATION, resources["owner"], resources["bank_id"],
        resources["document_id"], session_id=session_id, run_id=run_id,
    )
    run.begin(generation.build_params(GenerateStartBody(**body(resources))))

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE ops_runs RENAME TO saved_ops_runs"))
        connection.execute(text(
            "CREATE TABLE ops_runs (run_id VARCHAR(40) PRIMARY KEY, "
            "entrypoint VARCHAR(16), status VARCHAR(16), error_code VARCHAR(32))"
        ))
        connection.execute(text(
            "INSERT INTO ops_runs SELECT run_id, entrypoint, status, error_code FROM saved_ops_runs"
        ))
    try:
        generation.recover_interrupted_generation()
        with SessionLocal() as db:
            session = db.get(ChatSession, session_id)
            assert session.run_status == "interrupted" and session.run_id == run_id

        if association == "overwritten":
            monkeypatch.setattr(chat, "current_run_id", lambda: None)
            monkeypatch.setattr(chat, "detect_intent", lambda *_a, **_k: {
                "intent": "qa", "confidence": "high",
            })
            monkeypatch.setattr(chat, "get_skill", lambda _mode: SimpleNamespace(
                run=lambda _ctx: {"reply": "合成答复", "done": True},
            ))
            response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                                   json={"message": "普通问题", "mode": "qa"})
            assert response.status_code == 200, response.text
            with SessionLocal() as db:
                session = db.get(ChatSession, session_id)
                assert session.run_status == "done" and session.run_id != run_id
        else:
            with SessionLocal.begin() as db:
                db.delete(db.get(ChatSession, session_id))
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT status FROM ops_runs WHERE run_id = :run_id"
            ), {"run_id": run_id}).scalar_one() == "running"
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE ops_runs"))
            connection.execute(text("ALTER TABLE saved_ops_runs RENAME TO ops_runs"))

    generation.recover_interrupted_generation()
    with SessionLocal() as db:
        row = db.get(OpsRun, run_id)
        assert row.status == "unknown" and row.error_code == "EXECUTION_INTERRUPTED"


def test_restart_reconciles_failed_chat_without_overwriting_terminal_or_unrelated_runs(
    client, teacher, resources,
):
    session_id = resources["session_id"]
    with SessionLocal() as db:
        run_id = chat._begin_run(db, session_id, resources["owner"]).run_id
    run = GenerationRun(
        RunEntrypoint.CONVERSATION, resources["owner"], resources["bank_id"],
        resources["document_id"], session_id=session_id, run_id=run_id,
    )
    run.begin(generation.build_params(GenerateStartBody(**body(resources))))
    ledger = RunLedger()
    terminal_id = ledger.accept(
        entrypoint=RunEntrypoint.CONVERSATION, owner_user_id=resources["owner"],
        bank_id=resources["bank_id"], document_id=resources["document_id"],
        session_id=session_id, requested_count=1,
    )
    ledger.fail(terminal_id, error_code=RunErrorCode.EXECUTION_ERROR)
    unrelated_id = ledger.accept(
        entrypoint=RunEntrypoint.PARAMETERIZED, owner_user_id=resources["owner"],
        bank_id=resources["bank_id"], document_id=resources["document_id"], requested_count=1,
    )
    with SessionLocal.begin() as db:
        db.get(ChatSession, session_id).run_status = "failed"

    generation.recover_interrupted_generation()

    with SessionLocal() as db:
        assert db.get(ChatSession, session_id).run_status == "failed"
        row = db.get(OpsRun, run_id)
        assert row.status == "unknown" and row.error_code == "EXECUTION_INTERRUPTED"
        assert db.get(OpsRun, terminal_id).status == "failed"
        assert db.get(OpsRun, unrelated_id).status == "accepted"


def test_restart_reconciles_failed_task_with_unfinished_ledger(client, teacher, resources, monkeypatch):
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *_args, **_kwargs: None)
    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    with SessionLocal.begin() as db:
        task = db.get(GenerationTask, response.json()["task_id"])
        task.status = "failed"  # 模拟任务已提交、台账尚未收尾时进程退出。
        run_id = task.run_id

    generation.recover_interrupted_generation()
    with SessionLocal() as db:
        assert db.get(GenerationTask, response.json()["task_id"]).status == "failed"
        run = db.get(OpsRun, run_id)
        assert run.status == "unknown" and run.error_code == "EXECUTION_INTERRUPTED"


def test_restart_reconciles_canceled_chat_before_executor_stops(client, teacher, resources):
    with SessionLocal() as db:
        session = chat._begin_run(db, resources["session_id"], resources["owner"])
        run_id = session.run_id
    run = GenerationRun(
        RunEntrypoint.CONVERSATION, resources["owner"], resources["bank_id"],
        resources["document_id"], session_id=resources["session_id"], run_id=run_id,
    )
    run.begin(generation.build_params(GenerateStartBody(**body(resources))))
    response = client.post(f"/api/chat/sessions/{resources['session_id']}/cancel", headers=teacher)
    assert response.status_code == 202

    generation.recover_interrupted_generation()
    with SessionLocal() as db:
        session = db.get(ChatSession, resources["session_id"])
        row = db.get(OpsRun, run_id)
        assert session.run_status == "canceled" and session.canceled_run_id == run_id
        assert row.status == "unknown" and row.error_code == "EXECUTION_INTERRUPTED"

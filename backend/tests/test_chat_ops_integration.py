"""对话 SQL 会话与运维台账的事务、取消和运行关联。"""
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine
from app.models import ChatMessage, ChatSession, GenerationBatch, OpsRun
from app.models import Question as SavedQuestion
from app.models.ops_run import RunEntrypoint, RunErrorCode, RunStatus
from app.api import chat
from app.services import generation, phoenix_tracing
from app.services.generation_lifecycle import GenerationRun
from app.services.ops_runs import RunConflictError, RunLedger
from app.services.rag import chat_flow, question_gen
from test_generation_runs import post_chat, records
from test_generation_runs import resources as resources


@pytest.fixture(params=[False, True], ids=["no-tracing", "with-tracing"])
def conversation_trace(request, monkeypatch, client):
    """请求开始后启用追踪，覆盖继承旧上下文的同会话后续请求。"""
    if request.param:
        from app.config import settings
        from test_phoenix_tracing import CaptureSender

        monkeypatch.setattr(phoenix_tracing, "_Sender", CaptureSender)
        assert phoenix_tracing.configure(settings.model_copy(update={"phoenix_enabled": True}))
    yield
    if request.param:
        phoenix_tracing.shutdown()


@pytest.mark.parametrize("committed", [False, True])
def test_chat_uncertain_commit_preserves_only_confirmed_facts(
    client, teacher, resources, monkeypatch, committed,
):
    original_complete = GenerationRun.complete_in_transaction
    original_commit = Session.commit

    def complete(run, db, batch_id):
        original_complete(run, db, batch_id)
        db.info["simulate_uncertain_chat_commit"] = True

    def commit(db):
        if db.info.pop("simulate_uncertain_chat_commit", False):
            if committed:
                original_commit(db)
            raise SQLAlchemyError("synthetic uncertain chat commit")
        return original_commit(db)

    monkeypatch.setattr(GenerationRun, "complete_in_transaction", complete)
    monkeypatch.setattr(Session, "commit", commit)
    assert post_chat(client, teacher, resources).status_code == 503

    row, = records()
    assert row.status == ("completed" if committed else "unknown")
    assert row.delivered_count == (2 if committed else None)
    assert (row.batch_id is not None) == committed
    with SessionLocal() as db:
        session = db.get(ChatSession, resources["session_id"])
        assert session.run_id == row.run_id
        assert session.run_status == ("done" if committed else "failed")
        assert db.scalar(select(func.count()).select_from(GenerationBatch)) == int(committed)
        assert db.scalar(select(func.count()).select_from(SavedQuestion)) == 2 * int(committed)
        assert db.scalar(select(func.count()).select_from(ChatMessage)) == 2 * int(committed)


def test_canceled_generation_cannot_overwrite_successor_ledger(
    client, teacher, resources, monkeypatch, conversation_trace,
):
    original = chat_flow.generate_questions
    seen = []

    def generate(*args, **kwargs):
        with SessionLocal() as db:
            seen.append(db.get(ChatSession, resources["session_id"]).run_id)
        if len(seen) == 1:
            assert client.post(
                f"/api/chat/sessions/{resources['session_id']}/cancel", headers=teacher,
            ).status_code == 202
            successor = post_chat(client, teacher, resources)
            assert successor.status_code == 409
            assert successor.json()["detail"]["code"] == "CHAT_BUSY"
        return original(*args, **kwargs)

    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    previous = post_chat(client, teacher, resources)
    assert previous.status_code == 200 and previous.json()["batch_id"] is None
    assert previous.json()["questions"] == []
    successor = post_chat(client, teacher, resources)
    assert successor.status_code == 200 and successor.json()["batch_id"]
    assert len(seen) == 2 and seen[0] != seen[1]

    with SessionLocal() as db:
        old, new = (db.get(OpsRun, run_id) for run_id in seen)
        session = db.get(ChatSession, resources["session_id"])
        assert old.status == "canceled" and old.error_code == "USER_CANCELED"
        assert old.batch_id is None and old.delivered_count == 0
        assert new.status == "completed" and new.delivered_count == 2
        assert session.run_id == new.run_id and session.canceled_run_id == old.run_id
        assert session.run_status == "done"
        assert db.scalar(select(func.count()).select_from(GenerationBatch)) == 1
        assert db.scalar(select(func.count()).select_from(ChatMessage)) == 2


def test_cancel_before_handled_generation_error_is_recorded_as_canceled(
    client, teacher, resources, monkeypatch,
):
    def generate(*args, **kwargs):
        assert client.post(
            f"/api/chat/sessions/{resources['session_id']}/cancel", headers=teacher,
        ).status_code == 202
        raise question_gen.NeedConfirmError("单选题", 1, 2)

    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    response = post_chat(client, teacher, resources)
    assert response.status_code == 200 and "暂停" in response.json()["reply"]
    row, = records()
    assert row.status == "canceled" and row.error_code == "USER_CANCELED"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0


def test_chat_session_ledger_and_phoenix_share_run_id(client, teacher, resources, monkeypatch):
    from app.config import settings
    from test_phoenix_tracing import CaptureSender, attrs, spans

    sender = CaptureSender()
    monkeypatch.setattr(phoenix_tracing, "_Sender", lambda *args: sender)
    assert phoenix_tracing.configure(settings.model_copy(update={"phoenix_enabled": True}))
    original = chat_flow.generate_questions
    seen = []

    def generate(*args, **kwargs):
        run_id = phoenix_tracing.current_run_id()
        with SessionLocal() as db:
            session = db.get(ChatSession, resources["session_id"])
            row = db.get(OpsRun, run_id)
            assert session.run_id == run_id and row.status == "running"
            seen.append(run_id)
        return original(*args, **kwargs)

    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    try:
        response = post_chat(client, teacher, resources)
        assert response.status_code == 200
        row, = records()
        assert seen == [row.run_id] and row.status == "completed"
        root, = spans(sender)
        assert attrs(root)["mathcraft.run_id"] == row.run_id
    finally:
        phoenix_tracing.shutdown()


@pytest.mark.parametrize("outcome,expected", [
    ("empty", "NO_PERSISTABLE_QUESTIONS"),
    ("insufficient", "NEED_CONFIRM"),
])
def test_no_batch_turn_and_failure_become_visible_in_one_commit(
    client, teacher, resources, monkeypatch, outcome, expected,
):
    if outcome == "empty":
        monkeypatch.setattr(generation.question_review, "review_questions", lambda *a, **k: (
            [], generation.question_review.ReviewStats(),
        ))
    else:
        def insufficient(*args, **kwargs):
            raise question_gen.NeedConfirmError("单选题", 1, 2)

        monkeypatch.setattr(chat_flow, "generate_questions", insufficient)

    original_commit = Session.commit
    observations = []

    def observe_commit(db):
        completed = [
            item for item in db.identity_map.values()
            if isinstance(item, ChatSession) and item.id == resources["session_id"]
            and item.run_status == "done"
        ]
        run_id = completed[0].run_id if completed else None
        original_commit(db)
        if run_id:
            with SessionLocal() as reader:
                chat_session = reader.get(ChatSession, resources["session_id"])
                row = reader.get(OpsRun, run_id)
                observations.append((chat_session.run_status, row.status, row.error_code))

    monkeypatch.setattr(Session, "commit", observe_commit)
    assert post_chat(client, teacher, resources).status_code == 200
    assert observations == [("done", "failed", expected)]


def test_deleted_active_session_preserves_uncertain_ledger_until_executor_stops(
    client, teacher, student, resources, monkeypatch,
):
    assert post_chat(client, teacher, resources).status_code == 200
    previous, = records()
    previous_id = previous.run_id
    assert previous.status == "completed"
    original_generate = chat_flow.generate_questions
    during_deletion = []

    def generate(*args, **kwargs):
        url = f"/api/chat/sessions/{resources['session_id']}"
        assert client.delete(url, headers=student).status_code == 404
        with SessionLocal() as reader:
            session = reader.get(ChatSession, resources["session_id"])
            row = reader.get(OpsRun, session.run_id)
        assert row.status == "running"
        run_id = row.run_id

        assert client.delete(url, headers=teacher).status_code == 204
        generation.recover_interrupted_generation()
        with SessionLocal() as reader:
            assert reader.get(ChatSession, resources["session_id"]) is None
            row = reader.get(OpsRun, run_id)
            assert reader.get(OpsRun, previous_id).status == "completed"
            during_deletion.append((row.status, row.error_code, row.delivered_count))
        return original_generate(*args, **kwargs)

    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    response = post_chat(client, teacher, resources)
    assert response.status_code == 200
    assert during_deletion == [("unknown", "OUTCOME_UNKNOWN", None)]
    _, row = records()
    assert row.status == "canceled" and row.error_code == "USER_CANCELED"


def test_delete_between_accept_and_start_cannot_restart_deleted_run(
    client, teacher, resources, monkeypatch,
):
    original_register = GenerationRun.register_accepted
    original_progress = chat._write_progress
    progress_after_deletion = []
    observed = []

    def register(run):
        original_register(run)
        with SessionLocal() as reader:
            row = reader.get(OpsRun, run.run_id)
            assert row.status == "accepted" and row.started_at is None
        assert client.delete(
            f"/api/chat/sessions/{resources['session_id']}", headers=teacher,
        ).status_code == 204
        with SessionLocal() as reader:
            row = reader.get(OpsRun, run.run_id)
            observed.append((row.status, row.error_code))

    def progress(session_id, run_id, percent, stage):
        if observed:
            with SessionLocal() as reader:
                progress_after_deletion.append(reader.get(OpsRun, run_id).status)
        return original_progress(session_id, run_id, percent, stage)

    monkeypatch.setattr(GenerationRun, "register_accepted", register)
    monkeypatch.setattr(chat, "_write_progress", progress)
    response = post_chat(client, teacher, resources)
    assert response.status_code == 200 and "暂停" in response.json()["reply"]
    assert observed == [("unknown", "OUTCOME_UNKNOWN")]
    assert progress_after_deletion == []
    row, = records()
    assert row.status == "canceled" and row.started_at is None


@pytest.mark.parametrize("committed", [False, True])
def test_no_batch_uncertain_commit_preserves_confirmed_facts(
    client, teacher, resources, monkeypatch, committed,
):
    monkeypatch.setattr(generation.question_review, "review_questions", lambda *a, **k: (
        [], generation.question_review.ReviewStats(),
    ))
    original_commit = Session.commit
    injected = []

    def commit(db):
        is_turn = any(
            isinstance(item, ChatSession) and item.id == resources["session_id"]
            and item.run_status == "done" for item in db.identity_map.values()
        )
        if is_turn and not injected:
            injected.append(True)
            if committed:
                original_commit(db)
            raise SQLAlchemyError("synthetic uncertain no-batch commit")
        return original_commit(db)

    monkeypatch.setattr(Session, "commit", commit)
    assert post_chat(client, teacher, resources).status_code == 503
    assert injected == [True]
    row, = records()
    assert row.status == ("failed" if committed else "unknown")
    assert row.error_code == ("NO_PERSISTABLE_QUESTIONS" if committed else "OUTCOME_UNKNOWN")
    assert row.delivered_count == (0 if committed else None)
    with SessionLocal() as reader:
        session = reader.get(ChatSession, resources["session_id"])
        assert session.run_status == ("done" if committed else "failed")
        assert reader.scalar(select(func.count()).select_from(ChatMessage)) == 2 * int(committed)


def test_delete_failure_rolls_back_session_and_ledger_together(
    client, teacher, resources, monkeypatch,
):
    original_generate = chat_flow.generate_questions
    original_commit = Session.commit
    observed = []

    def commit(db):
        if any(isinstance(item, ChatSession) for item in db.deleted):
            raise SQLAlchemyError("synthetic delete commit failure")
        return original_commit(db)

    def generate(*args, **kwargs):
        assert client.delete(
            f"/api/chat/sessions/{resources['session_id']}", headers=teacher,
        ).status_code == 503
        with SessionLocal() as reader:
            session = reader.get(ChatSession, resources["session_id"])
            row = reader.get(OpsRun, session.run_id)
            observed.append((session.run_status, row.status, row.error_code))
        return original_generate(*args, **kwargs)

    monkeypatch.setattr(Session, "commit", commit)
    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    assert post_chat(client, teacher, resources).status_code == 200
    assert observed == [("running", "running", None)]
    row, = records()
    assert row.status == "completed"


def test_delete_racing_executor_cancel_keeps_confirmed_cancellation(
    client, teacher, resources, monkeypatch,
):
    original_generate = chat_flow.generate_questions
    deleted = Event()
    delete_results = []
    threads = []

    def delete():
        try:
            response = client.delete(
                f"/api/chat/sessions/{resources['session_id']}", headers=teacher,
            )
            delete_results.append(response.status_code)
        finally:
            deleted.set()

    def before_write(conn, cursor, statement, parameters, context, executemany):
        if (not threads and statement.lstrip().lower().startswith("update ops_runs")
                and "USER_CANCELED" in parameters):
            thread = Thread(target=delete, daemon=True)
            threads.append(thread)
            thread.start()
            assert deleted.wait(10), "删除必须在取消使用旧快照写入前完成"

    def generate(*args, **kwargs):
        assert client.post(
            f"/api/chat/sessions/{resources['session_id']}/cancel", headers=teacher,
        ).status_code == 202
        return original_generate(*args, **kwargs)

    event.listen(engine, "before_cursor_execute", before_write)
    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    try:
        response = post_chat(client, teacher, resources)
        assert threads and deleted.wait(10)
    finally:
        event.remove(engine, "before_cursor_execute", before_write)
        for thread in threads:
            thread.join(timeout=10)
    assert delete_results == [204]
    assert response.status_code == 200 and "暂停" in response.json()["reply"]
    row, = records()
    assert row.status == "canceled" and row.error_code == "USER_CANCELED"


@pytest.mark.parametrize("changed_field", ["started_at", "error_code"])
@pytest.mark.parametrize("target_status", [RunStatus.RUNNING, RunStatus.FAILED])
def test_chat_ledger_rejects_stale_unknown_snapshot(
    resources, monkeypatch, changed_field, target_status,
):
    """相同状态和时间重新出现时，不能用旧快照覆盖较新的运行事实。"""
    observed_at = datetime(2200, 1, 1, tzinfo=timezone.utc)
    ledger = RunLedger()
    run_id = ledger.accept(
        entrypoint=RunEntrypoint.CONVERSATION, owner_user_id=resources["owner"],
        bank_id=resources["bank_id"], document_id=resources["document_id"],
        session_id=resources["session_id"], requested_count=2, observed_at=observed_at,
    )
    initial_code = (RunErrorCode.OUTCOME_UNKNOWN if changed_field == "started_at"
                    else RunErrorCode.EXECUTION_INTERRUPTED)
    ledger.unknown(run_id, error_code=initial_code, observed_at=observed_at)
    monkeypatch.setattr(chat, "utcnow", lambda: observed_at + timedelta(minutes=1))
    interleaved = []

    def before_write(conn, cursor, statement, parameters, context, executemany):
        if interleaved or not statement.lstrip().lower().startswith("update ops_runs"):
            return
        interleaved.append(True)
        if changed_field == "started_at":
            ledger.start(run_id, observed_at=observed_at)
        ledger.unknown(run_id, error_code=RunErrorCode.OUTCOME_UNKNOWN, observed_at=observed_at)
        with SessionLocal() as reader:
            row = reader.get(OpsRun, run_id)
            assert row.status == "unknown" and row.error_code == "OUTCOME_UNKNOWN"
            assert row.last_observed_at == observed_at
            assert row.started_at == (observed_at if changed_field == "started_at" else None)

    code = RunErrorCode.NO_PERSISTABLE_QUESTIONS if target_status == RunStatus.FAILED else None
    conflict = None
    event.listen(engine, "before_cursor_execute", before_write)
    try:
        try:
            with SessionLocal.begin() as db:
                chat._transition_chat_ledger(
                    db, resources["session_id"], resources["owner"], run_id, target_status,
                    code=code,
                )
        except RunConflictError as exc:
            conflict = exc
    finally:
        event.remove(engine, "before_cursor_execute", before_write)

    assert interleaved == [True]
    with SessionLocal() as reader:
        row = reader.get(OpsRun, run_id)
        assert row.status == "unknown" and row.error_code == "OUTCOME_UNKNOWN"
        assert row.last_observed_at == observed_at
        assert row.started_at == (observed_at if changed_field == "started_at" else None)
    assert conflict is not None

    # 重新读取后可以继续转换，已有开始时间必须得到保留。
    with SessionLocal.begin() as db:
        chat._transition_chat_ledger(
            db, resources["session_id"], resources["owner"], run_id, target_status, code=code,
        )
    with SessionLocal() as reader:
        row = reader.get(OpsRun, run_id)
        assert row.status == target_status
        if changed_field == "started_at":
            assert row.started_at == observed_at

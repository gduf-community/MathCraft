"""运行台账的公开写入接口：仅使用独立 SQLite 和合成业务事实。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import create_engine, delete, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Bank, ChatSession, Document, GenerationBatch, OpsRun, Question, User
from app.models.ops_run import RunEntrypoint, RunErrorCode
from app.services import ops_runs, phoenix_tracing
from app.services.ops_runs import RunConflictError, RunLedger

T0 = datetime(2026, 11, 13, tzinfo=timezone.utc)
T1, T2, T3 = (T0 + timedelta(seconds=n) for n in (1, 2, 3))


@dataclass
class Store:
    engine: Engine
    sessions: sessionmaker[Session]
    ledger: RunLedger

    def accept(self, **overrides) -> str:
        fields = dict(entrypoint=RunEntrypoint.PARAMETERIZED, owner_user_id="u_owner",
                      bank_id="bank_test", document_id="doc_test", requested_count=2,
                      observed_at=T0)
        fields.update(overrides)
        return self.ledger.accept(**fields)

    def facts(self, run_id: str) -> dict:
        with self.sessions() as db:
            row = db.get(OpsRun, run_id)
            assert row is not None
            return {column.name: getattr(row, column.name) for column in OpsRun.__table__.columns}


@pytest.fixture
def store(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'ops.sqlite').as_posix()}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: sqlite3.Connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as db:
        db.add_all([
            User(id=uid, account=uid, password_hash="synthetic-unused-hash", role="teacher",
                 identity="教师", display_name="合成账号") for uid in ("u_owner", "u_other")
        ])
        db.flush()
        db.add(Bank(id="bank_test", name="合成题库", code="fake-bank", creator_id="u_other"))
        db.flush()
        db.add(Document(id="doc_test", bank_id="bank_test", name="synthetic.md", format="MD",
                        size_bytes=1, storage_path="synthetic/unused.md", status="ready",
                        uploader_id="u_owner"))
        db.flush()
        db.add(ChatSession(id="chat_test", user_id="u_owner", bank_id="bank_test",
                           document_id="doc_test"))
    yield Store(engine, sessions, RunLedger(sessions))
    engine.dispose()


def add_batch(db: Session, *, batch_id="batch_test", count=2, owner="u_owner") -> None:
    db.add(GenerationBatch(id=batch_id, user_id=owner, bank_id="bank_test",
                           document_id="doc_test", mode="parametric", question_count=count,
                           status="done"))
    db.flush()
    db.add_all([
        Question(id=f"q_{batch_id}_{n}", batch_id=batch_id, bank_id="bank_test",
                 document_id="doc_test", type="single", score=5, difficulty="中",
                 stem="合成题干，不能进入台账", answer="合成答案", analysis="合成解析",
                 created_by=owner) for n in range(count)
    ])
    db.flush()


def complete(store: Store, run_id: str, *, count=2, at=T2) -> None:
    with store.sessions.begin() as db:
        add_batch(db, count=count)
        store.ledger.complete_in_transaction(db, run_id, batch_id="batch_test", observed_at=at)


def test_disabled_phoenix_and_explicit_or_current_identifiers(store, monkeypatch):
    monkeypatch.setattr(phoenix_tracing, "_runtime", None)

    @phoenix_tracing.trace_run("parameterized")
    def accept_without_tracing():
        assert phoenix_tracing.current_run_id() is None
        return store.accept()

    first, second = accept_without_tracing(), accept_without_tracing()
    assert first.startswith("run_") and first != second
    monkeypatch.setattr(ops_runs, "current_run_id", lambda: "run_trace")
    assert store.accept() == "run_trace"
    assert store.accept(run_id="run_explicit") == "run_explicit"


def test_accept_owns_transaction_and_does_not_commit_another_session(store):
    with store.sessions() as caller:
        caller.add(User(id="u_pending", account="pending", password_hash="fake", role="teacher",
                        identity="教师", display_name="不应被提交"))
        run_id = store.accept()
        caller.rollback()
    assert store.facts(run_id)["status"] == "accepted"
    with store.sessions() as db:
        assert db.get(User, "u_pending") is None


def test_immutable_acceptance_replay_and_multiple_runs_in_one_session(store):
    fields = dict(entrypoint=RunEntrypoint.CONVERSATION, session_id="chat_test")
    run_id = store.accept(**fields)
    store.ledger.start(run_id, observed_at=T1)
    before = store.facts(run_id)
    assert store.accept(**fields, run_id=run_id, observed_at=T3) == run_id
    assert store.facts(run_id) == before
    assert store.accept(**fields) != run_id
    with pytest.raises(RunConflictError):
        store.accept(**fields, run_id=run_id, requested_count=3)


def test_concurrent_same_acceptance_is_idempotent(store):
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(lambda _: store.accept(run_id="run_replay"), range(8)))
    assert ids == ["run_replay"] * 8
    with store.sessions() as db:
        assert len(db.scalars(select(OpsRun)).all()) == 1


@pytest.mark.parametrize("fields", [
    {"owner_user_id": "u_missing"}, {"bank_id": "bank_missing"},
    {"document_id": "doc_missing"},
    {"entrypoint": RunEntrypoint.CONVERSATION, "session_id": "chat_test",
     "owner_user_id": "u_other"},
])
def test_accept_rejects_inconsistent_accounts_or_resources(store, fields):
    with pytest.raises(RunConflictError):
        store.accept(**fields)


@pytest.mark.parametrize("fields", [
    {"requested_count": 0}, {"requested_count": -1}, {"requested_count": True},
    {"requested_count": 1.5}, {"run_id": ""}, {"run_id": "正文 不得作为标识"},
    {"run_id": "x" * 41}, {"entrypoint": "qa"},
    {"entrypoint": RunEntrypoint.CONVERSATION}, {"session_id": "chat_test"},
    {"entrypoint": RunEntrypoint.CONVERSATION, "session_id": "chat_test", "task_id": "task_x"},
    {"observed_at": T0.replace(tzinfo=None)},
])
def test_accept_validates_counts_identifiers_context_and_time(store, fields):
    with pytest.raises(ValueError):
        store.accept(**fields)


def test_task_unique_but_null_task_and_session_are_allowed(store):
    store.accept(task_id="task_shared")
    with pytest.raises(RunConflictError):
        store.accept(task_id="task_shared")
    assert store.accept() != store.accept()


def test_utc_roundtrip_and_read_does_not_refresh_observation(store):
    local = T0.astimezone(timezone(timedelta(hours=8)))
    run_id = store.accept(observed_at=local)
    first = store.facts(run_id)
    assert first["accepted_at"] == T0
    assert first["accepted_at"].tzinfo == timezone.utc
    assert store.facts(run_id) == first
    assert first["started_at"] is first["finished_at"] is first["delivered_count"] is None


@pytest.mark.parametrize("outcome,code,count", [
    ("fail", "EXECUTION_ERROR", 0), ("cancel", "USER_CANCELED", 0),
    ("unknown", "OUTCOME_UNKNOWN", None),
])
def test_stop_evidence_and_repeated_writes(store, outcome, code, count):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)
    getattr(store.ledger, outcome)(run_id, observed_at=T2)
    facts = store.facts(run_id)
    expected_status = {"fail": "failed", "cancel": "canceled", "unknown": "unknown"}[outcome]
    assert facts["status"] == expected_status
    assert facts["error_code"] == code and facts["delivered_count"] == count
    assert facts["finished_at"] == (None if outcome == "unknown" else T2)
    getattr(store.ledger, outcome)(run_id, observed_at=T3)
    assert store.facts(run_id) == facts


def test_failure_before_execution_has_no_start_time(store):
    run_id = store.accept()
    store.ledger.fail(run_id, error_code=RunErrorCode.TASK_SUBMISSION_ERROR, observed_at=T1)
    assert store.facts(run_id)["started_at"] is None


@pytest.mark.parametrize("stop", ["fail", "cancel"])
@pytest.mark.parametrize("next_step", ["start", "fail", "cancel", "unknown"])
def test_confirmed_stops_cannot_change_or_restart(store, stop, next_step):
    run_id = store.accept()
    getattr(store.ledger, stop)(run_id, observed_at=T1)
    before = store.facts(run_id)
    if next_step == stop:
        getattr(store.ledger, next_step)(run_id, observed_at=T2)
    else:
        with pytest.raises(RunConflictError):
            getattr(store.ledger, next_step)(run_id, observed_at=T2)
    assert store.facts(run_id) == before


def test_unknown_can_be_resolved_with_fresh_execution_and_batch_evidence(store):
    run_id = store.accept()
    store.ledger.unknown(run_id, error_code=RunErrorCode.EXECUTION_INTERRUPTED, observed_at=T1)
    store.ledger.start(run_id, observed_at=T2)
    complete(store, run_id, at=T3)
    assert store.facts(run_id)["status"] == "completed"
    assert store.facts(run_id)["error_code"] is None


@pytest.mark.parametrize("outcome", ["complete", "fail", "cancel"])
def test_unknown_after_start_can_be_resolved_by_confirmed_outcome(store, outcome):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)
    store.ledger.unknown(run_id, observed_at=T2)
    if outcome == "complete":
        complete(store, run_id, at=T3)
    else:
        getattr(store.ledger, outcome)(run_id, observed_at=T3)
    assert store.facts(run_id)["status"] == {
        "complete": "completed", "fail": "failed", "cancel": "canceled",
    }[outcome]


def test_old_observations_and_duplicate_start_do_not_move_time_or_status(store):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)
    before = store.facts(run_id)
    store.ledger.start(run_id, observed_at=T3)
    store.ledger.cancel(run_id, observed_at=T0)
    assert store.facts(run_id) == before
    store.ledger.unknown(run_id, observed_at=T3)
    store.ledger.start(run_id, observed_at=T2)
    assert store.facts(run_id)["status"] == "unknown"


def test_batch_and_completion_are_invisible_until_caller_commits(store):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)
    with store.sessions() as db:
        add_batch(db)
        store.ledger.complete_in_transaction(db, run_id, batch_id="batch_test", observed_at=T2)
        assert db.get(OpsRun, run_id).status == "completed"
        assert store.facts(run_id)["status"] == "running"
        with store.sessions() as observer:
            assert observer.get(GenerationBatch, "batch_test") is None
        db.commit()
    assert store.facts(run_id)["batch_id"] == "batch_test"
    assert store.facts(run_id)["delivered_count"] == 2


@pytest.mark.parametrize("fail_at_commit", [False, True])
def test_business_failure_or_commit_failure_rolls_back_batch_and_completion(store, fail_at_commit):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)

    def reject_commit(connection):
        raise RuntimeError("synthetic commit failure")

    if fail_at_commit:
        event.listen(store.engine, "commit", reject_commit)
    try:
        with pytest.raises(RuntimeError), store.sessions.begin() as db:
            add_batch(db)
            store.ledger.complete_in_transaction(db, run_id, batch_id="batch_test", observed_at=T2)
            if not fail_at_commit:
                raise RuntimeError("synthetic business failure")
    finally:
        if fail_at_commit:
            event.remove(store.engine, "commit", reject_commit)
    assert store.facts(run_id)["status"] == "running"
    with store.sessions() as db:
        assert db.get(GenerationBatch, "batch_test") is None
        assert db.scalars(select(Question)).all() == []
    store.ledger.unknown(run_id, observed_at=T3)
    assert store.facts(run_id)["finished_at"] is None


@pytest.mark.parametrize("count", [0, 1, 2])
def test_completed_counts_are_saved_snapshots_including_zero(store, count):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)
    complete(store, run_id, count=count)
    facts = store.facts(run_id)
    with store.sessions.begin() as db:
        db.execute(delete(Question))
        db.execute(delete(GenerationBatch))
        store.ledger.complete_in_transaction(db, run_id, batch_id="batch_test", observed_at=T3)
    assert facts["delivered_count"] == count
    assert facts["requested_count"] == 2
    assert store.facts(run_id) == facts


@pytest.mark.parametrize("method", ["start", "fail", "cancel", "unknown"])
def test_saved_fact_survives_later_progress_reply_or_cancel_failures(store, method):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)
    complete(store, run_id)
    before = store.facts(run_id)
    getattr(store.ledger, method)(run_id, observed_at=T3)
    assert store.facts(run_id) == before


@pytest.mark.parametrize("reason", ["not_started", "other_owner", "wrong_count", "missing_batch"])
def test_completion_rejects_unproven_or_inconsistent_batch(store, reason):
    run_id = store.accept()
    if reason != "not_started":
        store.ledger.start(run_id, observed_at=T1)
    with store.sessions.begin() as db:
        if reason != "missing_batch":
            add_batch(db, owner="u_other" if reason == "other_owner" else "u_owner")
        if reason == "wrong_count":
            db.get(GenerationBatch, "batch_test").question_count = 3
            db.flush()
        with pytest.raises(RunConflictError):
            store.ledger.complete_in_transaction(db, run_id, batch_id="batch_test", observed_at=T2)
        db.rollback()


def test_completion_rejects_idle_session_and_another_batch(store):
    run_id = store.accept()
    with store.sessions() as db, pytest.raises(RunConflictError):
        store.ledger.complete_in_transaction(db, run_id, batch_id="batch_test")
    store.ledger.start(run_id, observed_at=T1)
    complete(store, run_id)
    with store.sessions.begin() as db, pytest.raises(RunConflictError):
        store.ledger.complete_in_transaction(db, run_id, batch_id="batch_other", observed_at=T3)


def test_completion_never_flushes_unrelated_caller_changes(store):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)
    with store.sessions(autoflush=True) as db:
        add_batch(db)
        pending = User(id="u_pending", account="pending", password_hash="fake", role="teacher",
                       identity="教师", display_name="调用方待处理")
        db.add(pending)
        store.ledger.complete_in_transaction(db, run_id, batch_id="batch_test", observed_at=T2)
        assert pending in db.new  # 即使调用方开启 autoflush，模块也不 flush 其余对象。
        db.rollback()
    with store.sessions() as db:
        assert db.get(User, "u_pending") is None
        assert db.get(GenerationBatch, "batch_test") is None


def test_completion_requires_all_batch_and_question_changes_flushed(store):
    run_id = store.accept()
    store.ledger.start(run_id, observed_at=T1)
    with store.sessions.begin() as db:
        add_batch(db, count=0)
        db.add(Question(id="q_pending", batch_id="batch_test", bank_id="bank_test",
                        document_id="doc_test", type="single", score=5, difficulty="中",
                        stem="尚未 flush", answer="合成", analysis="合成", created_by="u_owner"))
        with pytest.raises(RunConflictError, match="flush"):
            store.ledger.complete_in_transaction(db, run_id, batch_id="batch_test", observed_at=T2)
        db.rollback()


def test_resource_deletion_preserves_identifiers_and_owner_deletion_is_restricted(store):
    run_id = store.accept(entrypoint=RunEntrypoint.CONVERSATION, session_id="chat_test")
    with store.sessions.begin() as db:
        db.execute(delete(ChatSession))
        db.execute(delete(Document))
        db.execute(delete(Bank))
    assert store.facts(run_id)["session_id"] == "chat_test"
    assert store.facts(run_id)["document_id"] == "doc_test"
    with pytest.raises(IntegrityError), store.sessions.begin() as db:
        db.execute(delete(User).where(User.id == "u_owner"))


def test_only_structured_columns_and_safe_error_categories_are_stored(store):
    columns = {column["name"] for column in inspect(store.engine).get_columns("ops_runs")}
    assert columns == {
        "run_id", "entrypoint", "owner_user_id", "session_id", "task_id", "bank_id",
        "document_id", "batch_id", "status", "requested_count", "delivered_count", "error_code",
        "accepted_at", "started_at", "finished_at", "last_observed_at",
    }
    run_id = store.accept()
    marker = "synthetic private prompt and credential"
    with pytest.raises(ValueError) as error:
        store.ledger.fail(run_id, error_code=marker)
    assert marker not in str(error.value)
    assert marker not in repr(store.facts(run_id))
    with pytest.raises(ValueError):
        store.ledger.fail(run_id, error_code=RunErrorCode.USER_CANCELED)
    with pytest.raises(ValueError):
        store.ledger.unknown(run_id, error_code=RunErrorCode.MODEL_ERROR)

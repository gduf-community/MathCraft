"""三条真实 HTTP 路径的台账验收；模型、缓存与资料均为合成隔离数据。"""
from fastapi import BackgroundTasks
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api import chat
from app.db import SessionLocal
from app.models import Document, GenerationBatch, OpsRun, Question as SavedQuestion
from app.models.base import new_id
from app.models.ops_run import RunEntrypoint, RunErrorCode
from app.schemas.api import GenerateStartBody
from app.schemas.question import Question
from app.services import cache, generation, phoenix_tracing
from app.services.generation_lifecycle import GenerationRun, conversation_turn, mark_active_unknown
from app.services.ops_runs import RunLedger
from app.services.rag import chat_flow, llm, question_gen, slots
from conftest import create_bank, fake_question_chat_json


@pytest.fixture
def resources(client, teacher, monkeypatch):
    bank = create_bank(client, teacher)
    owner = client.get("/api/auth/me", headers=teacher).json()["user"]["id"]
    with SessionLocal.begin() as db:
        doc = Document(id=new_id("doc"), bank_id=bank["id"], name="synthetic.md", format="MD",
                       size_bytes=1, storage_path="synthetic-unused.md", status="ready",
                       uploader_id=owner)
        db.add(doc)
    client.put("/api/users/me/model-settings", headers=teacher,
               json={"deepseek_api_key": "fake-key-for-isolated-run-tests"})
    session_id = client.post("/api/chat/sessions", headers=teacher, json={
        "bank_id": bank["id"], "document_id": doc.id,
    }).json()["session_id"]

    def fake_generate(*args, **kwargs):
        data = fake_question_chat_json([{"content": "必须严格为 single；数量：2"}])
        count = sum(item.count for item in args[0].types)
        return [Question.model_validate(item) for item in data["questions"][:count]]

    monkeypatch.setattr(question_gen, "generate_questions", fake_generate)
    monkeypatch.setattr(chat_flow, "generate_questions", fake_generate)
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
        "intent": "generate", "confidence": "high",
    })
    return dict(bank_id=bank["id"], document_id=doc.id, owner=owner, session_id=session_id)


def body(resources):
    return dict(bank_id=resources["bank_id"], document_id=resources["document_id"],
                types=[{"type": "single", "count": 2}], difficulty="中", source_mode="variant_data")


def records():
    with SessionLocal() as db:
        return db.scalars(select(OpsRun).order_by(OpsRun.accepted_at)).all()


def post_chat(client, teacher, resources, **extra):
    return client.post(f"/api/chat/sessions/{resources['session_id']}/messages", headers=teacher,
                       json={"message": "出两道导数选择题，改数据，中等难度", **extra})


@pytest.mark.parametrize("path", ["/api/generate", "/api/generate/start"])
def test_parameterized_persists_actual_run_batch_and_identity(client, teacher, resources, path):
    response = client.post(path, headers=teacher, json=body(resources))
    assert response.status_code in (200, 202), response.text
    row, = records()
    assert row.status == "completed" and row.entrypoint == "parameterized"
    assert row.owner_user_id == resources["owner"] and row.bank_id == resources["bank_id"]
    assert row.document_id == resources["document_id"] and row.session_id is None
    assert row.requested_count == row.delivered_count == 2
    assert row.accepted_at <= row.started_at <= row.finished_at <= row.last_observed_at
    assert row.finished_at.utcoffset().total_seconds() == 0
    assert row.task_id == (response.json()["task_id"] if path.endswith("start") else None)
    with SessionLocal() as db:
        batch = db.get(GenerationBatch, row.batch_id)
        assert batch.user_id == row.owner_user_id
        assert db.scalar(select(func.count()).select_from(SavedQuestion)) == row.delivered_count


@pytest.mark.parametrize("path", ["/api/generate", "/api/generate/start"])
def test_unauthorized_and_unready_requests_are_not_accepted(
    client, teacher, student, resources, path,
):
    assert client.post(path, headers=student, json=body(resources)).status_code == 404
    with SessionLocal.begin() as db:
        db.get(Document, resources["document_id"]).status = "parsing"
    assert client.post(path, headers=teacher, json=body(resources)).status_code == 400
    assert records() == []


def test_busy_request_is_not_accepted(client, teacher, resources, monkeypatch):
    monkeypatch.setattr(generation, "acquire_lock", lambda _: False)
    assert client.post("/api/generate/start", headers=teacher,
                       json=body(resources)).status_code == 409
    assert records() == []


def test_async_accepted_precedes_execution_and_phoenix_reuses_id(
    client, teacher, resources, monkeypatch,
):
    from test_phoenix_tracing import CaptureSender, attrs, spans

    queued = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, function, *args, **kwargs:
                        queued.append((function, args, kwargs)))
    response = client.post("/api/generate/start", headers=teacher, json=body(resources))
    accepted, = records()
    assert response.status_code == 202
    assert accepted.status == "accepted" and accepted.started_at is None
    assert accepted.task_id == response.json()["task_id"]
    sender = CaptureSender()
    monkeypatch.setattr(phoenix_tracing, "_Sender", lambda *args: sender)
    from app.config import settings

    assert phoenix_tracing.configure(settings.model_copy(update={"phoenix_enabled": True}))
    try:
        function, args, kwargs = queued[0]
        assert kwargs["run_id"] == accepted.run_id
        function(*args, **kwargs)
        root, = spans(sender)
        assert attrs(root)["mathcraft.run_id"] == accepted.run_id
        completed, = records()
        assert completed.run_id == accepted.run_id and completed.status == "completed"
    finally:
        phoenix_tracing.shutdown()


def test_submission_failure_is_durable_and_releases_lock(client, teacher, resources, monkeypatch):
    def reject(*args, **kwargs):
        raise RuntimeError("synthetic submission failure")

    monkeypatch.setattr(BackgroundTasks, "add_task", reject)
    with pytest.raises(RuntimeError):
        client.post("/api/generate/start", headers=teacher, json=body(resources))
    row, = records()
    assert row.status == "failed" and row.error_code == "TASK_SUBMISSION_ERROR"
    assert row.started_at is None
    assert not cache.get_redis().exists(cache.PREFIX_GEN_LOCK.format(user_id=resources["owner"]))


@pytest.mark.parametrize("exception,code", [
    (llm.LLMError("synthetic-private-error"), "MODEL_ERROR"),
    (question_gen.NeedConfirmError("单选题", 1, 2), "NEED_CONFIRM"),
    (ValueError("synthetic-private-error"), "GENERATION_ERROR"),
    (RuntimeError("synthetic-private-error"), "EXECUTION_ERROR"),
])
@pytest.mark.parametrize("path", ["/api/generate", "/api/generate/start", "chat"])
def test_confirmed_execution_errors_use_safe_classification(
    client, teacher, resources, monkeypatch, exception, code, path,
):
    def reject(*args, **kwargs):
        raise exception

    monkeypatch.setattr(question_gen, "generate_questions", reject)
    monkeypatch.setattr(chat_flow, "generate_questions", reject)
    try:
        if path == "chat":
            response = post_chat(client, teacher, resources)
        else:
            response = client.post(path, headers=teacher, json=body(resources))
        assert "synthetic-private-error" not in response.text
    except type(exception):
        assert path == "/api/generate" or path == "chat"
    row, = records()
    assert row.status == "failed" and row.error_code == code
    assert row.delivered_count == 0 and row.batch_id is None
    assert row.started_at is not None and row.finished_at is not None


@pytest.mark.parametrize("path", ["/api/generate", "/api/generate/start", "chat"])
def test_zero_review_result_keeps_existing_batch_behavior(
    client, teacher, resources, monkeypatch, path,
):
    monkeypatch.setattr(generation.question_review, "review_questions", lambda *a, **k: (
        [], generation.question_review.ReviewStats(),
    ))
    if path == "chat":
        assert post_chat(client, teacher, resources).status_code == 200
    else:
        assert client.post(path, headers=teacher, json=body(resources)).status_code in (200, 202)
    row, = records()
    assert row.requested_count == 2 and row.delivered_count == 0
    assert row.status == ("failed" if path == "chat" else "completed")
    assert row.error_code == ("NO_PERSISTABLE_QUESTIONS" if path == "chat" else None)


@pytest.mark.parametrize("stage,expected", [
    ("before_commit", "failed"), ("commit_error", "unknown"), ("ack_lost", "completed"),
])
def test_batch_transaction_rollback_and_uncertain_commit(
    client, teacher, resources, monkeypatch, stage, expected,
):
    original_complete = GenerationRun.complete_in_transaction
    original_commit = Session.commit

    def prepare(self, db, batch_id):
        original_complete(self, db, batch_id)
        if stage == "before_commit":
            raise SQLAlchemyError("synthetic flush failure")
        db.info["synthetic_commit_failure"] = True

    def commit(db):
        if db.info.pop("synthetic_commit_failure", False):
            if stage == "ack_lost":
                original_commit(db)
            raise SQLAlchemyError("synthetic commit failure")
        return original_commit(db)

    monkeypatch.setattr(GenerationRun, "complete_in_transaction", prepare)
    monkeypatch.setattr(Session, "commit", commit)
    response = client.post("/api/generate", headers=teacher, json=body(resources))
    assert response.status_code == 503
    row, = records()
    assert row.status == expected
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GenerationBatch)) == (
            1 if stage == "ack_lost" else 0
        )
        assert db.scalar(select(func.count()).select_from(SavedQuestion)) == (
            2 if stage == "ack_lost" else 0
        )
    if expected == "unknown":
        assert row.finished_at is None and row.delivered_count is None


def test_chat_reply_commit_failure_preserves_saved_batch(client, teacher, resources, monkeypatch):
    from app.models import ChatMessage

    original = Session.commit

    def commit(db):
        if any(isinstance(item, ChatMessage) and item.role == "assistant" for item in db.new):
            raise SQLAlchemyError("synthetic reply failure")
        return original(db)

    monkeypatch.setattr(Session, "commit", commit)
    assert post_chat(client, teacher, resources).status_code == 503
    row, = records()
    assert row.status == "completed" and row.delivered_count == 2
    with SessionLocal() as db:
        assert db.get(GenerationBatch, row.batch_id) is not None
        assert db.scalar(select(func.count()).select_from(SavedQuestion)) == 2


def test_redis_result_failure_does_not_change_saved_fact(client, teacher, resources, monkeypatch):
    redis = cache.get_redis()
    original = redis.hset

    def hset(name, *args, **kwargs):
        if kwargs.get("mapping", {}).get("status") == "done":
            raise RedisConnectionError("synthetic progress failure")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(redis, "hset", hset)
    assert client.post("/api/generate/start", headers=teacher,
                       json=body(resources)).status_code == 202
    row, = records()
    assert row.status == "completed" and row.delivered_count == 2


@pytest.mark.parametrize("phase", ["generation", "review"])
def test_pause_request_is_not_terminal_until_executor_acknowledges(
    client, teacher, resources, monkeypatch, phase,
):
    def request_pause():
        response = client.post(f"/api/chat/sessions/{resources['session_id']}/cancel",
                               headers=teacher)
        assert response.status_code == 202
        assert records()[0].status == "running"

    if phase == "generation":
        original = chat_flow.generate_questions

        def generate(*args, **kwargs):
            request_pause()
            return original(*args, **kwargs)

        monkeypatch.setattr(chat_flow, "generate_questions", generate)
    else:
        def review(db, user_id, questions, *args, **kwargs):
            request_pause()
            kwargs["progress"](80, "synthetic review")
            return questions, generation.question_review.ReviewStats()

        monkeypatch.setattr(generation.question_review, "review_questions", review)
    response = post_chat(client, teacher, resources)
    assert response.status_code == 200
    assert "暂停" in response.json()["reply"]
    assert response.json()["questions"] == [] and response.json()["batch_id"] is None
    row, = records()
    assert row.status == "canceled" and row.error_code == "USER_CANCELED"


def test_overlapping_turn_is_rejected_after_ownership_check(
    client, teacher, student, resources,
):
    with conversation_turn(resources["session_id"]):
        response = post_chat(client, teacher, resources)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "CHAT_BUSY"
        assert post_chat(client, student, resources).status_code == 404
    assert records() == []
    assert post_chat(client, teacher, resources).status_code == 200


@pytest.mark.parametrize("kind", ["missing", "switch", "qa", "data", "mismatch"])
def test_non_generation_messages_never_create_runs(client, teacher, resources, monkeypatch, kind):
    extra = {}
    if kind == "missing":
        monkeypatch.setattr(slots, "chat_json", lambda *a, **k: {})
    elif kind == "switch":
        extra = dict(mode="creative", switch_only=True)
    elif kind in {"qa", "data"}:
        from app.services.rag.skills import ChatSkill

        monkeypatch.setattr(chat, "get_skill", lambda mode: ChatSkill(
            mode, mode, lambda ctx: {"reply": "synthetic reply", "done": True},
        ))
        extra = dict(mode=kind)
        monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
            "intent": kind, "confidence": "high",
        })
    else:
        monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
            "intent": "creative", "confidence": "high",
        })
    assert post_chat(client, teacher, resources, **extra).status_code == 200
    assert records() == []


@pytest.mark.parametrize("mode,count", [("generate", 2), ("creative", 1)])
def test_same_session_multiple_actual_generations_have_distinct_runs(
    client, teacher, resources, monkeypatch, mode, count,
):
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
        "intent": mode, "confidence": "high",
    })
    for _ in range(2):
        assert post_chat(client, teacher, resources, mode=mode).status_code == 200
    rows = records()
    assert len(rows) == 2 and rows[0].run_id != rows[1].run_id
    assert all(row.status == "completed" and row.session_id == resources["session_id"]
               for row in rows)
    assert all(row.requested_count == count for row in rows)
    assert all(row.delivered_count == count for row in rows)
    assert rows[0].batch_id != rows[1].batch_id


def test_interrupt_and_shutdown_only_mark_current_process_runs(resources):
    params = generation.build_params(GenerateStartBody(**body(resources)))
    run = GenerationRun(RunEntrypoint.PARAMETERIZED, resources["owner"],
                        resources["bank_id"], resources["document_id"])
    with pytest.raises(KeyboardInterrupt), run.observe():
        run.begin(params)
        raise KeyboardInterrupt
    interrupted = records()[0]
    assert interrupted.status == "unknown" and interrupted.error_code == "EXECUTION_INTERRUPTED"
    pending = GenerationRun(RunEntrypoint.PARAMETERIZED, resources["owner"],
                            resources["bank_id"], resources["document_id"])
    pending.accept(params)
    historical_id = RunLedger().accept(
        entrypoint=RunEntrypoint.PARAMETERIZED, owner_user_id=resources["owner"],
        bank_id=resources["bank_id"], document_id=resources["document_id"], requested_count=2,
    )
    mark_active_unknown()
    with SessionLocal() as db:
        assert db.get(OpsRun, pending.run_id).status == "unknown"
        assert db.get(OpsRun, historical_id).status == "accepted"

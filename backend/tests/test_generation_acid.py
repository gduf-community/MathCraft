"""出题与对话的 SQL 权威、取消和事务边界回归。"""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from redis.exceptions import RedisError
from sqlalchemy import event

from app.api import chat
from app.db import SessionLocal
from app.errors import AppError
from app.models import Bank, BankMember, ChatMessage, ChatSession, Document, GenerationBatch
from app.models import Question as QuestionRow
from app.models.base import new_id
from app.models.generation_task import GenerationTask
from app.schemas.api import GenerateStartBody
from app.schemas.question import Question
from app.services import cache, generation, question_review
from conftest import create_bank


def resources(client, teacher, db):
    """只建立 SQL ready 文档，所有模型与 Redis 均由公共夹具隔离。"""
    bank = create_bank(client, teacher)
    user_id = client.get("/api/auth/me", headers=teacher).json()["user"]["id"]
    doc = Document(
        id=new_id("doc"), bank_id=bank["id"], name="事务测试.md", format="MD",
        size_bytes=1, storage_path="fake-test-only.md", status="ready", uploader_id=user_id,
    )
    db.add(doc)
    db.commit()
    client.put("/api/users/me/model-settings", headers=teacher,
               json={"deepseek_api_key": "fake-acid-test-key"})
    body = {
        "bank_id": bank["id"], "document_id": doc.id,
        "types": [{"type": "single", "count": 1}], "difficulty": "中",
        "scope": "导数", "source_mode": "variant_data",
    }
    return user_id, body


def session_for(client, teacher, body):
    response = client.post("/api/chat/sessions", headers=teacher, json={
        "bank_id": body["bank_id"], "document_id": body["document_id"],
    })
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def test_ownerless_cache_never_grants_progress(client, teacher):
    cache.get_redis().hset(generation._task_key("orphan"), mapping={"status": "done"})
    assert generation.read_task("orphan", user_id="another-user") is None


def test_progress_cache_failure_is_nonblocking(client, teacher, db, monkeypatch):
    user_id, body = resources(client, teacher, db)
    task = generation.accept_task(db, user_id, GenerateStartBody(**body))
    task.status = "running"
    db.commit()

    def fail():
        raise RedisError("fake-cache-unavailable")

    monkeypatch.setattr(cache, "get_redis", fail)
    generation._write_progress(task.id, 20, "处理中", run_id=task.run_id)
    assert generation.read_task(task.id, user_id)["progress"] == 20


def test_canceled_chat_never_persists_turn(client, teacher, db, monkeypatch):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)

    def run(ctx):
        canceled = client.post(f"/api/chat/sessions/{session_id}/cancel", headers=teacher)
        assert canceled.status_code == 202
        return {"reply": "不应写入", "done": True, "slot_state": {"scope": "错误更新"}}

    monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
        "intent": "generate", "confidence": "high",
    })
    monkeypatch.setattr(chat, "get_skill", lambda mode: SimpleNamespace(run=run))
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "出题"})
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.query(ChatMessage).filter_by(session_id=session_id).count() == 0
    assert db.query(GenerationBatch).count() == 0
    assert json.loads(db.get(ChatSession, session_id).slot_state_json or "{}") == {}


def one_question():
    return Question(type="single", score=5, difficulty="中", stem="导数事务测试题",
                    options=[{"label": "A", "text": "1"}, {"label": "B", "text": "2"}],
                    answer="A", analysis="测试解析", knowledgePoint="导数")


def fake_generation(monkeypatch, hook=None):
    def generate(*args, **kwargs):
        if hook:
            hook()
        return [one_question()]

    monkeypatch.setattr(generation, "get_hyde", lambda *a, **k: None)
    monkeypatch.setattr(generation.question_gen, "generate_questions", generate)


def fake_chat(monkeypatch, hook=None, questions=False):
    def run(ctx):
        if hook:
            hook(ctx)
        return {"reply": "模型完成", "done": True,
                "slot_state": {"scope": "导数", "difficulty": "中",
                               "types": [{"type": "single", "count": 1}]},
                "questions": [one_question().model_dump()] if questions else []}

    monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
        "intent": "generate", "confidence": "high",
    })
    monkeypatch.setattr(chat, "get_skill", lambda mode: SimpleNamespace(run=run))


def test_acceptance_commits_before_dispatch_and_redis_loss_cannot_release_gate(
    client, teacher, db, monkeypatch,
):
    user_id, body = resources(client, teacher, db)

    def queued(task_id, owner, api_key, request, **kwargs):
        with SessionLocal() as other:
            row = other.get(GenerationTask, task_id)
            assert row.user_id == owner == user_id
            assert row.status == "queued"
            assert row.run_id == kwargs["run_id"]

    monkeypatch.setattr(generation, "run_generation_task", queued)
    first = client.post("/api/generate/start", headers=teacher, json=body)
    assert first.status_code == 202, first.text
    task_id = first.json()["task_id"]
    cache.get_redis().flushall()
    second = client.post("/api/generate/start", headers=teacher, json=body)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "GENERATION_BUSY"
    assert generation.read_task(task_id, user_id)["done"] is False
    assert generation.read_task(task_id, "wrong-owner") is None
    assert generation.read_task(task_id) is None


def test_parallel_acceptance_is_serialized_by_sql_user_row(client, teacher, db):
    user_id, body = resources(client, teacher, db)
    barrier = Barrier(2)

    def accept():
        with SessionLocal() as other:
            barrier.wait(timeout=5)
            try:
                return generation.accept_task(other, user_id, GenerateStartBody(**body)).id
            except AppError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: accept(), range(2)))
    assert results.count("GENERATION_BUSY") == 1
    db.expire_all()
    assert db.query(GenerationTask).filter_by(user_id=user_id).count() == 1


def test_persist_batch_commit_false_defers_visibility_and_rollback(client, teacher, db):
    user_id, body = resources(client, teacher, db)
    params = generation.build_params(GenerateStartBody(**body))
    batch = generation.persist_batch(
        db, user_id, body["bank_id"], body["document_id"], "parametric", params, None,
        [one_question()], commit=False,
    )
    with SessionLocal() as other:
        assert other.get(GenerationBatch, batch.id) is None
    db.rollback()
    assert db.query(GenerationBatch).count() == db.query(QuestionRow).count() == 0


def test_task_succeeds_without_redis_and_cannot_execute_twice(client, teacher, db, monkeypatch):
    user_id, body = resources(client, teacher, db)
    calls = []
    fake_generation(monkeypatch, lambda: calls.append(1))

    def unavailable():
        raise RedisError("fake-redis-unavailable")

    monkeypatch.setattr(cache, "get_redis", unavailable)
    task = generation.accept_task(db, user_id, GenerateStartBody(**body))
    for _ in range(2):
        generation.run_generation_task(task.id, user_id, "fake-test-key",
                                       GenerateStartBody(**body), run_id=task.run_id)
    result = generation.read_task(task.id, user_id)
    assert result["done"] and result["error"] is None and result["progress"] == 100
    assert len(result["questions"]) == 1
    db.expire_all()
    assert db.query(GenerationBatch).count() == db.query(QuestionRow).count() == len(calls) == 1


def test_old_task_token_cannot_extend_or_release_successor_lease(client):
    r = cache.get_redis()
    assert generation.acquire_lock("owner", "old-task:old-run")
    r.delete(cache.PREFIX_GEN_LOCK.format(user_id="owner"))
    assert generation.acquire_lock("owner", "new-task:new-run")
    assert not generation.renew_lock("owner", "old-task:old-run")
    assert not generation.release_lock("owner", "old-task:old-run")
    assert r.get(cache.PREFIX_GEN_LOCK.format(user_id="owner")) == "new-task:new-run"
    assert generation.renew_lock("owner", "new-task:new-run")
    assert generation.release_lock("owner", "new-task:new-run")


@pytest.mark.parametrize("change", ["document", "bank", "membership", "run"])
def test_task_revalidates_after_model_before_final_write(
    client, teacher, db, monkeypatch, change,
):
    user_id, body = resources(client, teacher, db)
    task = generation.accept_task(db, user_id, GenerateStartBody(**body))
    task_id, original_run = task.id, task.run_id

    def invalidate():
        with SessionLocal() as other:
            if change == "document":
                other.delete(other.get(Document, body["document_id"]))
            elif change == "bank":
                other.get(Bank, body["bank_id"]).status = "deleted"
            elif change == "membership":
                other.query(BankMember).filter_by(bank_id=body["bank_id"], user_id=user_id).delete()
            else:
                other.get(GenerationTask, task_id).run_id = new_id("run")
            other.commit()

    fake_generation(monkeypatch, invalidate)
    generation.run_generation_task(task_id, user_id, "fake-test-key", GenerateStartBody(**body),
                                   run_id=original_run)
    db.expire_all()
    assert db.query(GenerationBatch).count() == db.query(QuestionRow).count() == 0
    assert db.get(GenerationTask, task_id).status == ("running" if change == "run" else "failed")


def test_task_batch_and_done_state_rollback_together(client, teacher, db, monkeypatch):
    user_id, body = resources(client, teacher, db)
    task = generation.accept_task(db, user_id, GenerateStartBody(**body))
    fake_generation(monkeypatch)
    original = generation.persist_batch

    def fail_after_flush(*args, **kwargs):
        assert kwargs["commit"] is False
        original(*args, **kwargs)
        raise RuntimeError("fake-commit-boundary-failure")

    monkeypatch.setattr(generation, "persist_batch", fail_after_flush)
    generation.run_generation_task(task.id, user_id, "fake-test-key", GenerateStartBody(**body),
                                   run_id=task.run_id)
    db.expire_all()
    assert db.query(GenerationBatch).count() == db.query(QuestionRow).count() == 0
    assert db.get(GenerationTask, task.id).status == "failed"
    assert generation.read_task(task.id, user_id)["batch_id"] is None


def test_restart_marks_tasks_and_chat_interrupted_without_models(client, teacher, db, monkeypatch):
    user_id, body = resources(client, teacher, db)
    task = generation.accept_task(db, user_id, GenerateStartBody(**body))
    session_id = session_for(client, teacher, body)
    started = chat._begin_run(db, session_id, user_id)
    run_id = started.run_id
    calls = []
    fake_generation(monkeypatch, lambda: calls.append(1))
    generation.recover_interrupted_generation()
    db.expire_all()
    assert db.get(GenerationTask, task.id).status == "interrupted"
    assert db.get(ChatSession, session_id).run_status == "interrupted"
    assert chat._is_canceled(session_id, run_id)
    assert generation.read_task(task.id, user_id)["done"]
    assert calls == []
    retry = generation.accept_task(db, user_id, GenerateStartBody(**body))
    assert retry.id != task.id


def test_chat_uses_sql_slots_mode_and_pending_even_with_stale_redis(client, teacher, db, monkeypatch):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    s = db.get(ChatSession, session_id)
    s.slot_state_json = json.dumps({"scope": "SQL范围"})
    s.mode = "qa"
    s.pending_message = "SQL待续内容"
    s.pending_images_json = "[]"
    db.commit()
    cache.get_redis().hset(chat._slot_key(session_id), mapping={
        "slot_state": json.dumps({"scope": "错误Redis范围"}), "mode": "data",
        "pending_message": "错误Redis请求",
    })
    seen = []

    def run(ctx):
        seen.append((ctx.message, ctx.slot_state))
        return {"reply": "完成", "done": True}

    monkeypatch.setattr(chat, "get_skill", lambda mode: SimpleNamespace(run=run))
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
        "intent": "qa", "confidence": "high",
    })
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "切换", "mode": "qa", "switch_only": True})
    assert response.status_code == 200, response.text
    assert seen == [("SQL待续内容", {"scope": "SQL范围"})]
    db.expire_all()
    assert db.get(ChatSession, session_id).pending_message is None
    assert db.get(ChatSession, session_id).mode == "qa"


def test_cancel_old_run_then_start_new_does_not_revive_old_run(client, teacher, db, monkeypatch):
    user_id, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    old = chat._begin_run(db, session_id, user_id)
    old_run = old.run_id
    assert client.post(f"/api/chat/sessions/{session_id}/cancel", headers=teacher).status_code == 202
    new = chat._begin_run(db, session_id, user_id)
    assert new.run_id != old_run
    assert new.canceled_run_id == old_run
    assert chat._is_canceled(session_id, old_run)
    assert not chat._is_canceled(session_id, new.run_id)
    chat._end_failed_run(session_id, old_run)
    db.expire_all()
    assert db.get(ChatSession, session_id).run_status == "running"
    with pytest.raises(AppError) as caught:
        chat._begin_run(db, session_id, user_id)
    assert caught.value.code == "CHAT_BUSY"


def test_review_has_no_pending_writes_and_cancel_prevents_entire_turn(
    client, teacher, db, monkeypatch,
):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    fake_chat(monkeypatch, questions=True)

    def review(review_db, user_id, questions, *args, **kwargs):
        assert not review_db.new and not review_db.dirty
        assert client.post(f"/api/chat/sessions/{session_id}/cancel", headers=teacher).status_code == 202
        return questions, question_review.ReviewStats()

    monkeypatch.setattr(question_review, "review_questions", review)
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "出题"})
    assert response.status_code == 200, response.text
    assert response.json()["questions"] == []
    db.expire_all()
    assert db.query(ChatMessage).count() == db.query(GenerationBatch).count() == 0


def test_chat_commit_failure_rolls_back_batch_messages_and_slots(client, teacher, db, monkeypatch):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    fake_chat(monkeypatch, questions=True)

    def reject_assistant(mapper, connection, target):
        if target.role == "assistant":
            raise RuntimeError("fake-assistant-write-failure")

    event.listen(ChatMessage, "before_insert", reject_assistant)
    try:
        with pytest.raises(RuntimeError, match="fake-assistant-write-failure"):
            client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                        json={"message": "出题"})
    finally:
        event.remove(ChatMessage, "before_insert", reject_assistant)
    db.expire_all()
    assert db.query(ChatMessage).count() == db.query(GenerationBatch).count() == 0
    assert db.query(QuestionRow).count() == 0
    assert json.loads(db.get(ChatSession, session_id).slot_state_json) == {}
    assert db.get(ChatSession, session_id).run_status == "failed"


def test_canceled_old_response_cannot_overwrite_new_completed_turn(client, teacher, db, monkeypatch):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    endpoint = f"/api/chat/sessions/{session_id}/messages"
    seen_runs = []

    def supersede(ctx):
        with SessionLocal() as other:
            seen_runs.append(other.get(ChatSession, session_id).run_id)
        if len(seen_runs) == 1:
            assert client.post(f"/api/chat/sessions/{session_id}/cancel", headers=teacher).status_code == 202
            newer = client.post(endpoint, headers=teacher, json={"message": "新一轮"})
            assert newer.status_code == 409
            assert newer.json()["detail"]["code"] == "CHAT_BUSY"

    fake_chat(monkeypatch, supersede, questions=True)
    older = client.post(endpoint, headers=teacher, json={"message": "被取消的旧一轮"})
    assert older.status_code == 200 and older.json()["batch_id"] is None
    assert older.json()["questions"] == []
    newer = client.post(endpoint, headers=teacher, json={"message": "新一轮"})
    assert newer.status_code == 200 and newer.json()["batch_id"]
    db.expire_all()
    assert db.query(GenerationBatch).count() == db.query(QuestionRow).count() == 1
    messages = db.query(ChatMessage).filter_by(session_id=session_id).all()
    assert len(messages) == 2 and messages[0].content == "新一轮"
    session = db.get(ChatSession, session_id)
    assert session.run_id == seen_runs[1] and session.canceled_run_id == seen_runs[0]
    assert session.run_status == "done"


@pytest.mark.parametrize("route", ["async", "sync", "chat"])
def test_successful_results_remain_readable_with_sql_state(
    client, teacher, db, monkeypatch, route,
):
    user_id, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    fake_generation(monkeypatch)
    fake_chat(monkeypatch, questions=True)
    if route == "chat":
        def unavailable():
            raise RedisError("fake-redis-unavailable")

        monkeypatch.setattr(cache, "get_redis", unavailable)
        response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                               json={"message": "出题"})
        assert response.status_code == 200, response.text
        batch_id = response.json()["batch_id"]
        assert len(response.json()["questions"]) == 1
    elif route == "async":
        response = client.post("/api/generate/start", headers=teacher, json=body)
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]
        cache.get_redis().flushall()
        progress = client.get(f"/api/generate/progress/{task_id}", headers=teacher)
        assert progress.status_code == 200, progress.text
        assert progress.json()["done"] and not progress.json()["error"]
        batch_id = progress.json()["batch_id"]
        assert len(progress.json()["questions"]) == 1
        assert generation.read_task(task_id, user_id)["batch_id"] == batch_id
    else:
        response = client.post("/api/generate", headers=teacher, json=body)
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1
        batch_id = db.query(GenerationBatch).one().id
    db.expire_all()
    assert db.query(GenerationBatch).filter_by(id=batch_id, user_id=user_id).count() == 1
    assert db.query(QuestionRow).filter_by(batch_id=batch_id).count() == 1
    if route == "chat":
        assert db.query(ChatMessage).filter_by(session_id=session_id).count() == 2
        assert db.get(ChatSession, session_id).run_status == "done"
        assert json.loads(db.get(ChatSession, session_id).slot_state_json)["scope"] == "导数"


@pytest.mark.parametrize("path", ["/api/generate", "/api/chat/sessions/{session_id}/messages"])
def test_sync_and_chat_final_write_reject_deleted_document(client, teacher, db, monkeypatch, path):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)

    def remove(*args):
        with SessionLocal() as other:
            other.delete(other.get(Document, body["document_id"]))
            other.commit()

    fake_generation(monkeypatch, remove)
    fake_chat(monkeypatch, remove, questions=True)
    response = client.post(path.format(session_id=session_id), headers=teacher,
                           json=body if path == "/api/generate" else {"message": "出题"})
    assert response.status_code == 404, response.text
    db.expire_all()
    assert db.query(GenerationBatch).count() == db.query(ChatMessage).count() == 0

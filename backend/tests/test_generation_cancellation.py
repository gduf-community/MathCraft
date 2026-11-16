"""参数化任务取消的真实 HTTP、SQL 发布与执行退出边界。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
from uuid import uuid4

from fastapi import BackgroundTasks
import pytest

from sqlalchemy import event

from app.db import SessionLocal, engine
from app.models import GenerationBatch, OpsRun, Question
from app.models.generation_task import GenerationTask
from app.schemas.api import GenerateStartBody
from app.services import generation
from test_generation_acid import fake_generation, resources


def enqueue(client, teacher, body, monkeypatch):
    """捕获真实入口派发，允许测试确定性控制后台开始时刻。"""
    queued = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, fn, *args, **kwargs:
                        queued.append((fn, args, kwargs)))
    response = client.post("/api/generate/start", headers=teacher, json=body)
    assert response.status_code == 202, response.text
    return response.json()["task_id"], queued


def execute(queued):
    function, args, kwargs = queued[0]
    function(*args, **kwargs)


def test_cancel_queued_is_idempotent_and_never_executes_models(
    client, teacher, db, monkeypatch,
):
    owner, body = resources(client, teacher, db)
    task_id, queued = enqueue(client, teacher, body, monkeypatch)
    calls = []
    fake_generation(monkeypatch, lambda: calls.append("model"))
    for _ in range(2):
        response = client.post(f"/api/generate/cancel/{task_id}", headers=teacher)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "canceled"
        assert response.json()["done"] and response.json()["execution_finished"]
    execute(queued)
    assert not calls
    with SessionLocal() as other:
        task = other.get(GenerationTask, task_id)
        assert other.get(OpsRun, task.run_id).status == "canceled"
        assert other.query(GenerationBatch).count() == 0
    assert generation.read_task(task_id, owner)["error"] is None


def test_cancel_waits_for_model_exit_blocks_start_and_discards_late_result(
    client, teacher, db, monkeypatch,
):
    owner, body = resources(client, teacher, db)
    task_id, queued = enqueue(client, teacher, body, monkeypatch)
    entered, release = Event(), Event()

    def blocked():
        entered.set()
        assert release.wait(10)

    fake_generation(monkeypatch, blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute, queued)
        try:
            assert entered.wait(10)
            response = client.post(f"/api/generate/cancel/{task_id}", headers=teacher)
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "canceling"
            assert not response.json()["done"]
            busy = client.post("/api/generate/start", headers=teacher, json=body)
            assert busy.status_code == 409
            assert busy.json()["detail"]["code"] == "GENERATION_BUSY"
            assert not generation.read_task(task_id, owner)["execution_finished"]
        finally:
            release.set()
        future.result(timeout=10)
    state = generation.read_task(task_id, owner)
    assert state["status"] == "canceled" and state["done"] and state["execution_finished"]
    with SessionLocal() as other:
        assert other.query(Question).count() == other.query(GenerationBatch).count() == 0
        assert other.get(OpsRun, other.get(GenerationTask, task_id).run_id).status == "canceled"
    assert client.post("/api/generate/start", headers=teacher, json=body).status_code == 202


def test_completed_result_remains_identifiable_for_clear(client, teacher, db, monkeypatch):
    owner, body = resources(client, teacher, db)
    task_id, queued = enqueue(client, teacher, body, monkeypatch)
    fake_generation(monkeypatch)
    execute(queued)
    response = client.post(f"/api/generate/cancel/{task_id}", headers=teacher)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["status"] == "done" and state["execution_finished"]
    assert len(state["questions"]) == 1
    assert client.post("/api/questions/batch-delete", headers=teacher, json={
        "question_ids": [q["id"] for q in state["questions"]],
    }).status_code == 204
    assert generation.read_task(task_id, owner)["questions"] == []
    assert client.get("/api/generate/batches/latest", headers=teacher).json()["questions"] == []


def test_cancel_returns_actual_remaining_ids_after_partial_batch_deletion(
    client, teacher, db, monkeypatch,
):
    _, body = resources(client, teacher, db)
    task_id, queued = enqueue(client, teacher, body, monkeypatch)
    fake_generation(monkeypatch)
    execute(queued)
    with SessionLocal.begin() as other:
        task = other.get(GenerationTask, task_id)
        existing = other.query(Question).one()
        remaining = Question(
            id="q_remaining", batch_id=task.batch_id, bank_id=existing.bank_id,
            document_id=existing.document_id, type=existing.type, score=existing.score,
            difficulty=existing.difficulty, stem="剩余题目", answer="A", analysis="解析",
            created_by=existing.created_by,
        )
        other.add(remaining)
        other.delete(existing)
        # 原始结果副本指向已删除题目，取消仍须返回 SQL 实际存活集合。
    response = client.post(f"/api/generate/cancel/{task_id}", headers=teacher)
    assert response.status_code == 200, response.text
    assert response.json()["question_ids"] == ["q_remaining"]


def test_request_id_replay_finds_original_and_does_not_dispatch_twice(
    client, teacher, db, monkeypatch,
):
    _, body = resources(client, teacher, db)
    body["request_id"] = str(uuid4())
    task_id, queued = enqueue(client, teacher, body, monkeypatch)
    replay = client.post("/api/generate/start", headers=teacher, json=body)
    assert replay.status_code == 202, replay.text
    assert replay.json()["task_id"] == task_id and len(queued) == 1
    found = client.get(f"/api/generate/requests/{body['request_id']}", headers=teacher)
    assert found.status_code == 200 and found.json()["task_id"] == task_id
    conflict = client.post("/api/generate/start", headers=teacher, json={**body, "scope": "极限"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "GENERATION_REQUEST_CONFLICT"


def test_cancel_and_request_lookup_do_not_disclose_another_owner(
    client, teacher, student, db, monkeypatch,
):
    _, body = resources(client, teacher, db)
    body["request_id"] = str(uuid4())
    task_id, _ = enqueue(client, teacher, body, monkeypatch)
    assert client.post(f"/api/generate/cancel/{task_id}", headers=student).status_code == 404
    assert client.get(f"/api/generate/requests/{body['request_id']}",
                      headers=student).status_code == 404


def test_cancel_survives_deleted_material_and_restart(client, teacher, db, monkeypatch):
    owner, body = resources(client, teacher, db)
    task_id, _ = enqueue(client, teacher, body, monkeypatch)
    with SessionLocal.begin() as other:
        task = other.get(GenerationTask, task_id)
        task.status = "canceling"
        task.document_id = "deleted-document"
    generation.recover_interrupted_generation()
    response = client.post(f"/api/generate/cancel/{task_id}", headers=teacher)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "interrupted"
    assert response.json()["execution_finished"]


@pytest.mark.parametrize("stage", ["hyde", "review"])
def test_cancel_between_stages_does_not_publish(client, teacher, db, monkeypatch, stage):
    _, body = resources(client, teacher, db)
    task_id, queued = enqueue(client, teacher, body, monkeypatch)
    fake_generation(monkeypatch)

    def cancel():
        response = client.post(f"/api/generate/cancel/{task_id}", headers=teacher)
        assert response.status_code == 202

    if stage == "hyde":
        monkeypatch.setattr(generation, "get_hyde", lambda *args, **kwargs: cancel())
        monkeypatch.setattr(generation.question_gen, "generate_questions",
                            lambda *args, **kwargs: pytest.fail("取消后不得生成"))
    else:
        original = generation.question_review.review_questions

        def review(*args, **kwargs):
            result = original(*args, **kwargs)
            cancel()
            return result

        monkeypatch.setattr(generation.question_review, "review_questions", review)
    execute(queued)
    with SessionLocal() as other:
        assert other.get(GenerationTask, task_id).status == "canceled"
        assert other.query(Question).count() == other.query(GenerationBatch).count() == 0


def test_cancel_contends_with_publication_and_observes_committed_result(
    client, teacher, db, monkeypatch,
):
    _, body = resources(client, teacher, db)
    task_id, queued = enqueue(client, teacher, body, monkeypatch)
    fake_generation(monkeypatch)
    publishing, release, cancel_entered = Event(), Event(), Event()
    original = generation.persist_batch

    def blocked_publication(*args, **kwargs):
        batch = original(*args, **kwargs)
        publishing.set()
        assert release.wait(10)
        return batch

    def observe_cancel(connection, cursor, statement, parameters, context, many):
        if current_thread().name.startswith("cancel-race") and statement.startswith("UPDATE users"):
            cancel_entered.set()

    def cancel():
        with SessionLocal() as other:
            from app.models import User

            owner = other.get(GenerationTask, task_id).user_id
            version = other.get(User, owner).auth_version
        return generation.cancel_task(task_id, owner, version)

    monkeypatch.setattr(generation, "persist_batch", blocked_publication)
    event.listen(engine, "before_cursor_execute", observe_cancel)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            execution = workers.submit(execute, queued)
            assert publishing.wait(10)
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="cancel-race") as cancels:
                cancellation = cancels.submit(cancel)
                try:
                    assert cancel_entered.wait(10)
                    assert not cancellation.done()
                finally:
                    release.set()
                state = cancellation.result(timeout=10)
            execution.result(timeout=10)
        assert state["status"] == "done" and len(state["questions"]) == 1
        with SessionLocal() as other:
            task = other.get(GenerationTask, task_id)
            assert other.get(OpsRun, task.run_id).status == "completed"
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observe_cancel)

"""真实 HTTP 路径验证对话轮次的取消、发布和恢复。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from app.api import chat
from app.db import SessionLocal
from app.models import ChatMessage, ChatRequest
from app.services import generation
from test_generation_runs import post_chat
from test_generation_runs import resources as resources


def test_cancel_before_send_is_durable_and_scoped(client, teacher, student, resources, monkeypatch):
    base = f"/api/chat/sessions/{resources['session_id']}"
    request_id = str(uuid4())
    url = f"{base}/requests/{request_id}"

    def unexpected(*args, **kwargs):
        raise AssertionError("tombstoned request entered model preflight")

    monkeypatch.setattr(chat, "_message_api_key", unexpected)
    assert client.get(url, headers=teacher).status_code == 404
    assert client.post(f"{base}/cancel", params={"request_id": request_id},
                       headers=student).status_code == 404
    expected = {"status": "canceled", "execution_finished": True, "batch_id": None, "result": None}
    for _ in range(2):
        canceled = client.post(f"{base}/cancel", params={"request_id": request_id}, headers=teacher)
        assert canceled.status_code == 202
        assert canceled.json() == expected
    assert client.get(url, headers=student).status_code == 404
    assert client.get(url, headers=teacher).json() == expected
    late = post_chat(client, teacher, resources, request_id=request_id)
    assert late.status_code == 200
    assert late.json()["reply"] == chat.chat_flow.PAUSED_REPLY
    assert client.get(f"{base}/requests/invalid", headers=teacher).status_code == 422
    assert client.post(f"{base}/cancel", params={"request_id": "invalid"},
                       headers=teacher).status_code == 422
    assert post_chat(client, teacher, resources, request_id="invalid").status_code == 422
    with SessionLocal() as db:
        assert db.query(ChatMessage).count() == 0


def test_cancel_waits_for_the_target_execution_to_exit(client, teacher, resources, monkeypatch):
    base = f"/api/chat/sessions/{resources['session_id']}"
    entered, release = Event(), Event()
    target, other = str(uuid4()), str(uuid4())

    def detect(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return {"intent": "generate", "confidence": "high"}

    monkeypatch.setattr(chat, "detect_intent", detect)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(post_chat, client, teacher, resources, request_id=target)
        try:
            assert entered.wait(15)
            assert client.get(f"{base}/requests/{target}", headers=teacher).json() == {
                "status": "running", "execution_finished": False, "batch_id": None, "result": None,
            }
            assert client.post(f"{base}/cancel", params={"request_id": other},
                               headers=teacher).json()["execution_finished"] is True
            assert client.get(f"{base}/requests/{target}", headers=teacher).json()["status"] == "running"
            for _ in range(2):
                assert client.post(f"{base}/cancel", params={"request_id": target},
                                   headers=teacher).json() == {
                    "status": "canceled", "execution_finished": False,
                    "batch_id": None, "result": None,
                }
            assert post_chat(client, teacher, resources, request_id=str(uuid4())).status_code == 409
        finally:
            release.set()
        assert pending.result(timeout=15).json()["reply"] == chat.chat_flow.PAUSED_REPLY
    assert client.get(f"{base}/requests/{target}", headers=teacher).json() == {
        "status": "canceled", "execution_finished": True, "batch_id": None, "result": None,
    }
    with SessionLocal() as db:
        assert db.query(ChatMessage).count() == 0


def test_published_batch_recovers_only_surviving_current_questions(
    client, teacher, resources, monkeypatch,
):
    base = f"/api/chat/sessions/{resources['session_id']}"
    request_id = str(uuid4())
    committed, release = Event(), Event()
    record_commit = chat.GenerationRun.committed

    def hold_after_commit(run):
        record_commit(run)
        committed.set()
        assert release.wait(15)

    monkeypatch.setattr(chat.GenerationRun, "committed", hold_after_commit)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(post_chat, client, teacher, resources, request_id=request_id)
        try:
            assert committed.wait(15)
            cancel = client.post(f"{base}/cancel", params={"request_id": request_id}, headers=teacher)
            assert cancel.status_code == 202
            published = cancel.json()
            assert published["status"] == "done"
            assert published["execution_finished"] is False
            assert published["result"]["questions"]
        finally:
            release.set()
        sent = pending.result(timeout=15)
    assert sent.status_code == 200, sent.text
    original = sent.json()
    assert published["result"] == original
    removed, survivor = original["questions"]
    assert removed["id"] and survivor["id"]

    def unexpected(*args, **kwargs):
        raise AssertionError("published request started a second execution")

    monkeypatch.setattr(chat, "detect_intent", unexpected)
    cancel = client.post(f"{base}/cancel", params={"request_id": request_id}, headers=teacher)
    assert cancel.status_code == 202
    assert cancel.json() == {
        "status": "done", "execution_finished": True,
        "batch_id": original["batch_id"], "result": original,
    }
    assert client.delete(f"/api/questions/{removed['id']}", headers=teacher).status_code == 204
    edited = client.put(f"/api/questions/{survivor['id']}", headers=teacher,
                        json={"stem": "Edited question stem"})
    assert edited.status_code == 200
    status = client.get(f"{base}/requests/{request_id}", headers=teacher).json()
    updated, = status["result"]["questions"]
    assert status["batch_id"] == original["batch_id"]
    assert updated["id"] == survivor["id"]
    assert updated["stem"] == "Edited question stem"
    assert updated["doc_name"] == "synthetic.md"
    assert post_chat(client, teacher, resources, request_id=request_id).json() == status["result"]
    assert client.post("/api/questions/batch-delete", headers=teacher,
                       json={"question_ids": [survivor["id"]]}).status_code == 204
    canceled = client.post(f"{base}/cancel", params={"request_id": request_id}, headers=teacher)
    assert canceled.json()["result"]["questions"] == []
    assert post_chat(client, teacher, resources, request_id=request_id).json()["questions"] == []
    with SessionLocal() as db:
        assert db.query(ChatMessage).count() == 2


def test_failed_request_and_restart_have_distinct_terminal_states(
    client, teacher, resources, monkeypatch,
):
    base = f"/api/chat/sessions/{resources['session_id']}"
    failed, interrupted = str(uuid4()), str(uuid4())
    monkeypatch.setattr(chat, "get_effective_deepseek_key", lambda *args: None)
    assert post_chat(client, teacher, resources, request_id=failed).status_code == 400
    with SessionLocal() as db:
        chat._begin_run(db, resources["session_id"], resources["owner"], request_id=interrupted)
    generation.recover_interrupted_generation()
    for request_id, state in ((failed, "failed"), (interrupted, "interrupted")):
        assert client.get(f"{base}/requests/{request_id}", headers=teacher).json() == {
            "status": state, "execution_finished": True, "batch_id": None, "result": None,
        }
    assert client.delete(base, headers=teacher).status_code == 204
    with SessionLocal() as db:
        assert db.query(ChatRequest).count() == 0

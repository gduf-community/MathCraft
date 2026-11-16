"""独立审查回归：凭据快照、缓存失效代际与答疑取消。"""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import httpx
import pytest

from app import db as db_module
from app.config import settings
from app.services import model_settings, secure_store
from app.services.generation_cancellation import GenerationCanceled
from app.services.rag import llm, qa, skills
from app.services.rag.chat_flow import ChatCanceled
from test_llm_merge_runtime import REAL_JSON, REAL_PLATFORM, runtime_sdk

A = ("fake-a-key", "https://a.example.test/v1", "a-model")
B = ("fake-b-key", "https://b.example.test/v1", "b-model")
MESSAGES = [{"role": "user", "content": "fixture prompt"}]


@pytest.mark.parametrize("mode", ["json", "text", "stream", "client"])
def test_legacy_effective_platform_key_keeps_original_runtime_after_rotation(
    runtime_sdk, monkeypatch, mode,
):
    current = [A]
    calls = []
    monkeypatch.setattr(llm, "get_platform_llm", lambda: current[0])
    db = SimpleNamespace(get=lambda *_: None)
    key = model_settings.get_effective_deepseek_key(db, "fake-user")
    current[0] = B

    def respond(request):
        calls.append((request.url.host, request.headers["authorization"],
                      json.loads(request.content)))
        if mode == "stream":
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content='data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}\n\n'
                        'data: [DONE]\n\n',
            )
        return httpx.Response(200, json={"choices": [{
            "index": 0, "message": {"role": "assistant", "content": '{"answer":"ok"}'},
            "finish_reason": "stop",
        }]})

    runtime_sdk(A, respond)
    runtime_sdk((A[0], B[1], B[2]), respond)
    if mode == "json":
        llm.chat_json(MESSAGES, key)
    elif mode == "text":
        llm.chat_text(MESSAGES, key)
    elif mode == "stream":
        list(llm.chat_stream(MESSAGES, key))
    else:
        llm.get_client(api_key=key).chat.completions.create(model=A[2], messages=MESSAGES)
    assert calls and calls[0][0] == "a.example.test"
    assert calls[0][1] == "Bearer fake-a-key"
    assert calls[0][2]["model"] == A[2]


@pytest.mark.parametrize("source", ["personal", "deployment"])
@pytest.mark.parametrize("require", [False, True])
def test_effective_runtime_snapshot_keeps_source_and_all_credentials(
    runtime_sdk, monkeypatch, source, require,
):
    platform_reads = []
    monkeypatch.setattr(settings, "deepseek_api_key", "fake-env-key")
    monkeypatch.setattr(settings, "deepseek_base_url", "https://env.example.test/v1")
    monkeypatch.setattr(settings, "deepseek_model", "env-model")

    def platform():
        platform_reads.append(1)
        return A if source == "personal" else None

    monkeypatch.setattr(llm, "get_platform_llm", platform)
    db = SimpleNamespace(get=lambda *_: SimpleNamespace(
        deepseek_api_key="fake-personal-key" if source == "personal" else None,
    ))
    getter = model_settings.require_deepseek_key if require else (
        model_settings.get_effective_deepseek_key
    )
    key = getter(db, "fake-user")
    expected = ("fake-personal-key", *A[1:]) if source == "personal" else (
        "fake-env-key", "https://env.example.test/v1", "env-model",
    )
    monkeypatch.setattr(llm, "get_platform_llm", lambda: pytest.fail("snapshot resolved twice"))
    runtime = llm.resolve_llm_runtime(key)
    assert runtime.credentials == expected
    assert runtime.source == source
    assert key == expected[0] and isinstance(key, str)
    assert expected[0] not in repr(key) + repr(runtime)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{
            "index": 0, "message": {"role": "assistant", "content": '{"answer":"ok"}'},
            "finish_reason": "stop",
        }]})

    runtime_sdk(expected, respond)
    assert llm.chat_json(MESSAGES, key) == {"answer": "ok"}
    assert json.loads(requests[0].content)["model"] == expected[2]
    assert requests[0].headers["authorization"] == f"Bearer {expected[0]}"
    assert len(platform_reads) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_pinned_platform_key_never_becomes_personal_fallback(runtime_sdk, monkeypatch, status):
    current = [A]
    monkeypatch.setattr(llm, "get_platform_llm", lambda: current[0])
    key = model_settings.require_deepseek_key(SimpleNamespace(get=lambda *_: None), "fake-user")
    current[0] = B
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "fixture denied"}})

    runtime_sdk(A, reject)
    runtime_sdk(B, lambda request: pytest.fail("platform key retried as personal"))
    with pytest.raises(llm.LLMError):
        llm.chat_json(MESSAGES, key)
    assert len(requests) == 1
    assert requests[0].url.host == "a.example.test"


@pytest.mark.parametrize("old_result", ["configured", "empty", "decrypt-error"])
def test_invalidation_prevents_inflight_old_read_from_republishing_cache(monkeypatch, old_result):
    started, release = Event(), Event()
    lock = Lock()
    reads = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, model, identity):
            with lock:
                reads.append(1)
                first = len(reads) == 1
            runtime = A if first else B
            row = SimpleNamespace(encrypted_key=runtime[0], base_url=runtime[1], model=runtime[2])
            if first:
                started.set()
                assert release.wait(5)
                if old_result == "empty":
                    return None
            return row

    def decrypt(value):
        if value == A[0] and old_result == "decrypt-error":
            raise ValueError("fixture old decrypt failure")
        return value

    monkeypatch.setattr(llm, "_platform_cache", None)
    monkeypatch.setattr(llm, "_platform_cached_at", 0.0)
    monkeypatch.setattr(db_module, "SessionLocal", FakeSession)
    monkeypatch.setattr(secure_store, "decrypt_secret", decrypt)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(REAL_PLATFORM)
        try:
            assert started.wait(5)
            llm.invalidate_platform_cache()
            assert REAL_PLATFORM() == B
        finally:
            release.set()
        future.result(timeout=5)
    assert REAL_PLATFORM() == B
    assert len(reads) == 2


def _ctx(canceled):
    return SimpleNamespace(
        session=SimpleNamespace(bank_id="fake-bank", document_id="fake-doc"),
        message="解释定义", history=[], api_key="fake-personal-key", doc_name="fake.pdf",
        progress_cb=lambda *_: None, cancel_check=canceled.is_set,
    )


def test_qa_skill_cancel_after_invalid_json_stops_sdk_retry(runtime_sdk, monkeypatch):
    canceled = Event()
    calls = []
    monkeypatch.setattr(llm, "get_platform_llm", lambda: None)
    monkeypatch.setattr(qa, "chat_json", REAL_JSON)
    monkeypatch.setattr(qa, "retrieve_for_generation", lambda *a, **k: [{"text": "fixture"}])

    def respond(request):
        calls.append(request)
        canceled.set()
        return httpx.Response(200, json={"choices": [{
            "index": 0, "message": {"role": "assistant", "content": '{"answer":'},
            "finish_reason": "stop",
        }]})

    runtime_sdk(("fake-personal-key", settings.deepseek_base_url, settings.deepseek_model), respond)
    with pytest.raises(ChatCanceled):
        skills.run_qa(_ctx(canceled))
    assert len(calls) == 1


@pytest.mark.parametrize("stage", ["before-retrieval", "retrieval", "model-direct"])
def test_qa_skill_cancellation_never_becomes_fallback_reply(monkeypatch, stage):
    canceled = Event()
    calls = []
    if stage == "before-retrieval":
        canceled.set()

    def retrieve(*args, **kwargs):
        calls.append("retrieve")
        if stage == "retrieval":
            canceled.set()
            return []
        return [{"text": "fixture"}]

    def model(*args, **kwargs):
        calls.append("model")
        raise GenerationCanceled("fixture direct cancel")

    monkeypatch.setattr(qa, "retrieve_for_generation", retrieve)
    monkeypatch.setattr(qa, "chat_json", model)
    with pytest.raises(ChatCanceled):
        skills.run_qa(_ctx(canceled))
    assert calls == ([] if stage == "before-retrieval" else (
        ["retrieve"] if stage == "retrieval" else ["retrieve", "model"]
    ))

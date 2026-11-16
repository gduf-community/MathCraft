"""平台三元组、鉴权回退与取消的合并回归；SDK 只访问内存 MockTransport。"""

import inspect
import json
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from app import db as db_module
from app.config import settings
from app.services import secure_store
from app.services.generation_cancellation import GenerationCanceled
from app.services.rag import llm

REAL_TEXT = llm.chat_text
REAL_JSON = llm.chat_json
REAL_STREAM = llm.chat_stream
REAL_PLATFORM = llm.get_platform_llm
MESSAGES = [{"role": "user", "content": "fixture prompt"}]
PLATFORM = ("fake-platform-key", "https://platform.example.test/v1", "platform-model")


def _completion(content: str = '{"answer": "ok"}') -> httpx.Response:
    return httpx.Response(200, json={"choices": [{
        "index": 0, "message": {"role": "assistant", "content": content},
        "finish_reason": "stop",
    }]})


@pytest.fixture
def runtime_sdk(monkeypatch, fake_models):
    """恢复真实模型入口并为每个运行三元组提供独立的假传输。"""
    monkeypatch.setattr(llm, "chat_text", REAL_TEXT)
    monkeypatch.setattr(llm, "chat_json", REAL_JSON)
    monkeypatch.setattr(llm, "chat_stream", REAL_STREAM)
    monkeypatch.setattr(llm, "get_platform_llm", lambda: PLATFORM)
    clients = {}
    monkeypatch.setattr(llm, "_clients", clients)

    def install(runtime, handler):
        clients[runtime] = OpenAI(
            api_key=runtime[0], base_url=runtime[1], max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    yield install
    for client in clients.values():
        client.close()


def _invoke(mode, check=None):
    if mode == "json":
        return llm.chat_json(MESSAGES, "fake-personal-key", 0, 73, False, check, thinking=True)
    if mode == "text":
        return llm.chat_text(
            MESSAGES, "fake-personal-key", 0.23, 73, False,
            {"type": "json_object"}, check, thinking=True,
        )
    return list(llm.chat_stream(
        MESSAGES, "fake-personal-key", 73, False, 0.23, check, thinking=True,
    ))


@pytest.mark.parametrize("mode", ["text", "json", "stream"])
@pytest.mark.parametrize("status", [401, 403])
def test_personal_auth_fallback_preserves_complete_runtime_and_parameters(
    runtime_sdk, monkeypatch, mode, status,
):
    first = ("fake-personal-key", "https://old.example.test/v1", "old-model")
    platform_values = iter([("fake-old-platform", *first[1:]), PLATFORM])
    monkeypatch.setattr(llm, "get_platform_llm", lambda: next(platform_values))
    calls = []

    def reject(request):
        calls.append((request.url.host, json.loads(request.content)))
        return httpx.Response(status, json={"error": {"message": "fixture auth failure"}})

    def success(request):
        calls.append((request.url.host, json.loads(request.content)))
        if mode == "stream":
            payload = {"choices": [{"index": 0, "delta": {"content": "ok"}}]}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                 content=f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n")
        return _completion()

    runtime_sdk(first, reject)
    runtime_sdk(PLATFORM, success)
    result = _invoke(mode)
    assert result == ({"answer": "ok"} if mode == "json" else (
        ['ok'] if mode == "stream" else '{"answer": "ok"}'
    ))
    assert [host for host, _body in calls] == ["old.example.test", "platform.example.test"]
    original, fallback = calls[0][1], calls[1][1]
    assert original["model"] == "old-model" and fallback["model"] == "platform-model"
    assert {k: v for k, v in original.items() if k != "model"} == {
        k: v for k, v in fallback.items() if k != "model"
    }
    assert fallback["messages"] == MESSAGES
    assert fallback["max_tokens"] == 73
    assert fallback["thinking"] == {"type": "enabled"}
    if mode != "json":
        assert fallback["temperature"] == 0.23


@pytest.mark.parametrize("mode", ["text", "json", "stream"])
def test_platform_auth_failure_has_no_recursive_fallback(runtime_sdk, mode):
    calls = []

    def reject(request):
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "fixture denied"}})

    runtime_sdk(("fake-personal-key", *PLATFORM[1:]), reject)
    runtime_sdk(PLATFORM, reject)
    with pytest.raises(llm.LLMError):
        _invoke(mode)
    assert len(calls) == 2


@pytest.mark.parametrize("mode", ["text", "json", "stream"])
def test_auth_failure_after_cancel_never_dispatches_platform(runtime_sdk, mode):
    canceled = Event()
    calls = []

    def check():
        if canceled.is_set():
            raise GenerationCanceled("fixture canceled")

    def reject(request):
        calls.append(request)
        canceled.set()
        return httpx.Response(401, json={"error": {"message": "fixture denied"}})

    runtime_sdk(("fake-personal-key", *PLATFORM[1:]), reject)
    runtime_sdk(PLATFORM, lambda request: pytest.fail("canceled fallback dispatched"))
    with pytest.raises(GenerationCanceled):
        _invoke(mode, check)
    assert len(calls) == 1


def test_json_repair_keeps_platform_runtime_after_auth_fallback(runtime_sdk):
    requests = []
    runtime_sdk(("fake-personal-key", *PLATFORM[1:]), lambda request: httpx.Response(
        403, json={"error": {"message": "fixture denied"}},
    ))

    def respond(request):
        requests.append(json.loads(request.content))
        return _completion('{"answer":' if len(requests) == 1 else '{"answer": "ok"}')

    runtime_sdk(PLATFORM, respond)
    assert llm.chat_json(
        MESSAGES, "fake-personal-key", max_tokens=10, thinking=True, temperature=0.12,
    ) == {
        "answer": "ok",
    }
    assert [item["max_tokens"] for item in requests] == [10, 16]
    assert all(item["model"] == PLATFORM[2] for item in requests)
    assert all(item["thinking"] == {"type": "enabled"} for item in requests)
    assert [item["temperature"] for item in requests] == [0.12, 0.3]


@pytest.mark.parametrize("thinking,off,expected", [
    (True, True, "enabled"), (False, False, "disabled"), (None, True, "disabled"),
    (None, False, None),
])
def test_explicit_thinking_takes_precedence(runtime_sdk, thinking, off, expected):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return _completion()

    runtime_sdk(PLATFORM, respond)
    llm.chat_json(MESSAGES, thinking_off=off, thinking=thinking)
    assert requests[0].get("thinking") == (
        {"type": expected} if expected is not None else None
    )


def test_public_signatures_preserve_cancel_position_and_keyword_only_thinking():
    for function, index in [(REAL_JSON, 5), (REAL_TEXT, 6), (REAL_STREAM, 5)]:
        params = list(inspect.signature(function).parameters.values())
        assert params[index].name == "cancel_check"
        assert params[index].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert params[index + 1].name == "thinking"
        assert params[index + 1].kind == inspect.Parameter.KEYWORD_ONLY


def test_client_cache_includes_url_and_model_and_supports_legacy_call(monkeypatch):
    created = []
    monkeypatch.setattr(llm, "_clients", {})
    monkeypatch.setattr(llm, "get_platform_llm", lambda: PLATFORM)
    monkeypatch.setattr(llm, "MetadataClient", lambda model: model)

    def constructor(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(llm, "OpenAI", constructor)
    one = llm.get_client(api_key="fake-personal-key")
    assert one is llm.get_client(runtime=("fake-personal-key", *PLATFORM[1:]))
    two = llm.get_client(runtime=("fake-personal-key", "https://new.example.test/v1", PLATFORM[2]))
    three = llm.get_client(runtime=("fake-personal-key", PLATFORM[1], "new-model"))
    assert one is not two and one is not three and two is not three
    assert len(created) == 3
    assert created[2]["http_client"] == "new-model"


@pytest.mark.parametrize("kind", ["configured", "empty", "decrypt-error"])
def test_platform_read_is_stubbed_cached_and_session_closed(monkeypatch, kind):
    events = []
    clock = [100.0]
    row = SimpleNamespace(encrypted_key="fake-encrypted", base_url=PLATFORM[1], model=PLATFORM[2])

    class FakeSession:
        def __enter__(self):
            events.append("enter")
            return self

        def get(self, model, identity):
            events.append("read")
            assert identity == 1
            return None if kind == "empty" else row

        def __exit__(self, *args):
            events.append("close")

    def decrypt(value):
        assert value == "fake-encrypted"
        if kind == "decrypt-error":
            raise ValueError("fixture decrypt failed")
        return PLATFORM[0]

    monkeypatch.setattr(db_module, "SessionLocal", FakeSession)
    monkeypatch.setattr(secure_store, "decrypt_secret", decrypt)
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(llm, "_platform_cache", None)
    monkeypatch.setattr(llm, "_platform_cached_at", 0.0)
    expected = PLATFORM if kind == "configured" else None
    assert REAL_PLATFORM() == expected
    assert REAL_PLATFORM() == expected
    assert events == ["enter", "read", "close"]
    clock[0] += 31
    assert REAL_PLATFORM() == expected
    assert events == ["enter", "read", "close"] * 2
    row.model = "rotated-model"
    llm.invalidate_platform_cache()
    assert REAL_PLATFORM() == ((*PLATFORM[:2], "rotated-model") if kind == "configured" else None)
    assert events == ["enter", "read", "close"] * 3


def test_runtime_resolution_falls_back_to_deployment_without_platform(monkeypatch):
    monkeypatch.setattr(llm, "get_platform_llm", lambda: None)
    monkeypatch.setattr(settings, "deepseek_api_key", "fake-deployment-key")
    assert llm.resolve_runtime() == (
        "fake-deployment-key", settings.deepseek_base_url, settings.deepseek_model,
    )
    assert llm.resolve_runtime("fake-personal-key")[0] == "fake-personal-key"

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
    monkeypatch.setattr(llm, "_thinking_variant_cache", {})
    monkeypatch.setattr(llm, "_thinking_off_cache", {})

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
    assert fallback["chat_template_kwargs"] == {"thinking": True}
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
    assert all(item["chat_template_kwargs"] == {"thinking": True} for item in requests)
    assert [item["temperature"] for item in requests] == [0.12, 0.3]


@pytest.mark.parametrize("thinking,off,expected", [
    (True, True, {"chat_template_kwargs": {"thinking": True}}),
    (False, False, {"thinking": {"type": "disabled"}}),
    (None, True, {"thinking": {"type": "disabled"}}),
    (None, False, {}),
])
def test_explicit_thinking_takes_precedence(runtime_sdk, thinking, off, expected):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return _completion()

    runtime_sdk(PLATFORM, respond)
    llm.chat_json(MESSAGES, thinking_off=off, thinking=thinking)
    actual = {
        key: requests[0][key] for key in ("thinking", "chat_template_kwargs") if key in requests[0]
    }
    assert actual == expected


@pytest.mark.parametrize("mode", ["text", "json", "stream"])
@pytest.mark.parametrize("cancel_after", [None, 1, 2, 3])
def test_thinking_probe_and_auth_fallback_share_cancellation_and_runtime(
    runtime_sdk, monkeypatch, mode, cancel_after,
):
    """个人探测遇鉴权失败后，平台独立探测；任一失败后取消都禁止下一次请求。"""
    first = ("fake-personal-key", "https://old.example.test/v1", "old-model")
    platform_values = iter([("fake-old-platform", *first[1:]), PLATFORM])
    monkeypatch.setattr(llm, "get_platform_llm", lambda: next(platform_values))
    canceled = Event()
    calls = []

    def check():
        if canceled.is_set():
            raise GenerationCanceled("fixture canceled during probe")

    def respond(request):
        body = json.loads(request.content)
        calls.append((request.url.host, request.headers["authorization"], body))
        if len(calls) == cancel_after:
            canceled.set()
        if "chat_template_kwargs" in body:
            return httpx.Response(400, json={"error": {"message": "unsupported thinking"}})
        if request.url.host == "old.example.test":
            return httpx.Response(401, json={"error": {"message": "fixture auth failure"}})
        if mode == "stream":
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content='data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}\n\n'
                        'data: [DONE]\n\n',
            )
        return _completion()

    runtime_sdk(first, respond)
    runtime_sdk(PLATFORM, respond)
    if cancel_after is not None:
        with pytest.raises(GenerationCanceled):
            _invoke(mode, check)
        assert len(calls) == cancel_after
        assert llm.thinking_variant(PLATFORM) is None
    else:
        result = _invoke(mode, check)
        assert result == ({"answer": "ok"} if mode == "json" else (
            ["ok"] if mode == "stream" else '{"answer": "ok"}'
        ))
        assert len(calls) == 4
        assert llm.thinking_variant(llm.LlmRuntime(*PLATFORM, source="platform")) == 1
    assert llm.thinking_variant(first) is None
    for index, (host, authorization, body) in enumerate(calls):
        runtime = first if index < 2 else PLATFORM
        assert host == ("old.example.test" if index < 2 else "platform.example.test")
        assert authorization == f"Bearer {runtime[0]}"
        assert body["model"] == runtime[2]
        assert body["max_tokens"] == 73
        assert body["messages"] == MESSAGES
        assert body["temperature"] == (0.7 if mode == "json" else 0.23)
        variant = llm.THINKING_ON_VARIANTS[index % 2]
        assert all(body[key] == value for key, value in variant.items())
        if mode == "stream":
            assert body["stream"] is True
        else:
            assert body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("thinking,rejections", [(True, 2), (False, 2)])
@pytest.mark.parametrize("cancel", [False, True])
def test_probe_bare_fallback_checks_cancellation_and_preserves_cache_strategy(
    runtime_sdk, thinking, rejections, cancel,
):
    """开启和关闭均遍历两种写法；裸调之前必须重新检查取消。"""
    canceled = Event()
    calls = []

    def check():
        if canceled.is_set():
            raise GenerationCanceled("fixture canceled before bare request")

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if "thinking" in body or "chat_template_kwargs" in body:
            if cancel and len(calls) == rejections:
                canceled.set()
            return httpx.Response(422, json={"error": {"message": "unsupported thinking"}})
        return _completion()

    runtime_sdk(PLATFORM, respond)
    if cancel:
        with pytest.raises(GenerationCanceled):
            llm.chat_json(MESSAGES, thinking=thinking, cancel_check=check)
        assert len(calls) == rejections
        assert llm._thinking_off_cache == {}
    else:
        assert llm.chat_json(MESSAGES, thinking=thinking, cancel_check=check) == {"answer": "ok"}
        assert len(calls) == rejections + 1
        assert "thinking" not in calls[-1] and "chat_template_kwargs" not in calls[-1]
        if thinking is False:
            assert llm._thinking_off_cache[(PLATFORM[1], PLATFORM[2])] == -1
            assert llm.chat_json(MESSAGES, thinking=False) == {"answer": "ok"}
            assert len(calls) == rejections + 2
            assert "thinking" not in calls[-1] and "chat_template_kwargs" not in calls[-1]


def test_probe_cache_and_json_latex_repair_survive_platform_fallback(runtime_sdk, monkeypatch):
    """预算递增、JSON 修复消息、平台快照及成功变体缓存跨鉴权回退共同保留。"""
    personal = llm.LlmRuntime(
        "fake-personal-key", "https://old.example.test/v1", "old-model", "personal",
    )
    calls = []
    platform_reads = []

    def platform():
        platform_reads.append(1)
        return PLATFORM

    monkeypatch.setattr(llm, "get_platform_llm", platform)

    def reject_personal(request):
        body = json.loads(request.content)
        calls.append((request.url.host, body))
        if body["max_tokens"] == 10:
            return _completion('{"answer":')
        return httpx.Response(403, json={"error": {"message": "fixture denied"}})

    platform_calls = []

    def respond_platform(request):
        body = json.loads(request.content)
        calls.append((request.url.host, body))
        platform_calls.append(body)
        if "chat_template_kwargs" in body:
            return httpx.Response(400, json={"error": {"message": "unsupported thinking"}})
        if len(platform_calls) < 4:
            return _completion('{"answer":')
        return _completion(r'{"answer":"\frac{1}{2} + \alpha"}')

    runtime_sdk(personal.credentials, reject_personal)
    runtime_sdk(PLATFORM, respond_platform)
    assert llm.chat_json(
        MESSAGES, llm.ResolvedApiKey(personal), max_tokens=10, retries=1,
        thinking=True, temperature=0.12,
    ) == {"answer": r"\frac{1}{2} + \alpha"}
    assert len(platform_reads) == 1
    assert [body["max_tokens"] for _, body in calls] == [10, 16, 16, 16, 25, 25]
    assert [body["temperature"] for _, body in calls] == [0.12, 0.3, 0.3, 0.3, 0.3, 0.3]
    assert all(body["model"] == PLATFORM[2] for body in platform_calls)
    assert all(body["thinking"] == {"type": "enabled"} for body in platform_calls[1:])
    assert platform_calls[-1]["messages"][1] == {"role": "assistant", "content": '{"answer":'}
    assert "请严格只输出合法 JSON" in platform_calls[-1]["messages"][-1]["content"]
    assert llm.thinking_variant(PLATFORM) == 1


@pytest.mark.parametrize("mode", ["json", "text", "stream"])
def test_thinking_off_probes_both_variants_and_reprobes_rejected_cache(
    runtime_sdk, monkeypatch, mode,
):
    current = [1]
    calls = []
    runtime = llm.LlmRuntime(*PLATFORM, source="platform")
    key = llm.ResolvedApiKey(runtime)
    monkeypatch.setattr(llm, "get_platform_llm", lambda: pytest.fail("snapshot resolved twice"))

    def respond(request):
        body = json.loads(request.content)
        variant = {field: body[field] for field in ("thinking", "chat_template_kwargs") if field in body}
        calls.append(variant)
        assert request.url.host == "platform.example.test"
        assert request.headers["authorization"] == "Bearer fake-platform-key"
        assert body["model"] == PLATFORM[2]
        assert body["max_tokens"] == 73
        if variant != llm.THINKING_OFF_VARIANTS[current[0]]:
            return httpx.Response(400, json={"error": {"message": "unsupported thinking"}})
        if mode == "stream":
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content='data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}\n\n'
                        'data: [DONE]\n\n',
            )
        return _completion()

    def invoke():
        if mode == "json":
            assert llm.chat_json(MESSAGES, key, max_tokens=73, thinking=False) == {"answer": "ok"}
        elif mode == "text":
            assert llm.chat_text(MESSAGES, key, max_tokens=73, thinking_off=True) == '{"answer": "ok"}'
        else:
            assert list(llm.chat_stream(MESSAGES, key, max_tokens=73, thinking_off=True)) == ["ok"]

    runtime_sdk(PLATFORM, respond)
    invoke()
    invoke()
    assert calls == [llm.THINKING_OFF_VARIANTS[i] for i in (0, 1, 1)]
    assert llm._thinking_off_cache[PLATFORM[1:]] == 1
    current[0] = 0
    invoke()
    assert calls[-2:] == [llm.THINKING_OFF_VARIANTS[i] for i in (1, 0)]
    assert llm._thinking_off_cache[PLATFORM[1:]] == 0


def test_thinking_off_reprobes_rejected_bare_cache(runtime_sdk):
    calls = []
    llm._thinking_off_cache[PLATFORM[1:]] = -1

    def respond(request):
        body = json.loads(request.content)
        variant = {field: body[field] for field in ("thinking", "chat_template_kwargs") if field in body}
        calls.append(variant)
        if variant != llm.THINKING_OFF_VARIANTS[1]:
            return httpx.Response(422, json={"error": {"message": "thinking parameter required"}})
        return _completion()

    runtime_sdk(PLATFORM, respond)
    assert llm.chat_json(MESSAGES, thinking=False) == {"answer": "ok"}
    assert calls == [{}, *llm.THINKING_OFF_VARIANTS]
    assert llm._thinking_off_cache[PLATFORM[1:]] == 1


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

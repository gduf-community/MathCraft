"""用 MockTransport 驱动原生 SDK，验证单次执行与 legacy 的兼容边界。"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

import httpx
import openai
import pytest

from app.errors import AppError
from app.services import agent_sdk, generation_observation
from app.services.rag import llm

_CHAT_JSON = llm.chat_json
_CHAT_TEXT = llm.chat_text
_CHAT_STREAM = llm.chat_stream
MESSAGES = [
    {"role": "system", "content": "按现有要求出题。"},
    {"role": "assistant", "content": "已有回复\n保留顺序"},
    {"role": "user", "content": "请返回 JSON。"},
]
FAKE_KEY = "test-only-fake-model-key"


def completion(content: str | None, *, refusal: str | None = None) -> httpx.Response:
    """构造 Chat Completions 服务端响应，保留真实 provider 解析流程。"""
    return httpx.Response(200, json={
        "id": "chatcmpl-fake", "created": 1, "model": "fake-model",
        "object": "chat.completion",
        "choices": [{
            "index": 0, "finish_reason": "stop", "logprobs": None,
            "message": {"role": "assistant", "content": content, "refusal": refusal},
        }],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    })


def failure(message: str, status: int = 400) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message, "type": "fake_error"}})


def event(delta: dict, finish_reason: str | None = None) -> bytes:
    payload = {
        "id": "chatcmpl-fake", "created": 1, "model": "fake-model",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


@dataclass
class TrackedStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    """记录真正 HTTP 流的关闭，并可在首个 delta 前后阻塞或出错。"""

    chunks: list[bytes]
    terminal: Literal["done", "error", "wait"] = "done"
    closed: bool = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks
        if self.terminal == "error":
            raise httpx.ReadError("thinking stream failed")

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield chunk
        if self.terminal == "error":
            raise httpx.ReadError("thinking stream failed")
        if self.terminal == "wait":
            await asyncio.Event().wait()

    def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        self.closed = True


def streamed(
    pieces: list[str], *, terminal: Literal["done", "error", "wait"] = "done",
    prefix: bool = True,
) -> tuple[httpx.Response, TrackedStream]:
    chunks = [event({"role": "assistant", "content": ""})] if prefix else []
    if prefix:
        chunks += [event({"reasoning_content": "此内容不应作为文本 delta 返回"})]
    chunks += [event({"content": piece}) for piece in pieces]
    if terminal == "done":
        chunks += [event({}, "stop"), b"data: [DONE]\n\n"]
    stream = TrackedStream(chunks, terminal)
    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
    return response, stream


@dataclass
class Wire:
    """同步与异步 OpenAI 客户端共享的纯内存服务端。"""

    backend: Literal["sdk", "legacy"] | None = "sdk"
    replies: list[httpx.Response | Exception] = field(default_factory=list)
    requests: list[dict] = field(default_factory=list)
    sync_clients: list[httpx.Client] = field(default_factory=list)
    async_clients: list[httpx.AsyncClient] = field(default_factory=list)
    loops: list[asyncio.AbstractEventLoop] = field(default_factory=list)
    loop_errors: list[dict] = field(default_factory=list)

    def respond(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://models.example.test/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
        self.requests.append(json.loads(request.content))
        assert self.replies, "模型调用次数超出预期"
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def assert_clean(self) -> None:
        assert all(client.is_closed for client in self.async_clients)
        assert all(loop.is_closed() for loop in self.loops)
        assert all(not asyncio.all_tasks(loop) for loop in self.loops)
        assert not self.loop_errors


@pytest.fixture
def wire(fake_models, monkeypatch) -> Iterator[Wire]:
    """撤销上层 llm mock；在实际 provider 的 HTTP 客户端底层注入 transport。"""
    import agents
    from agents.tracing import get_trace_provider

    from app.services import agent_tracing

    instance = Wire()
    monkeypatch.setattr(llm, "chat_json", _CHAT_JSON)
    monkeypatch.setattr(llm, "chat_text", _CHAT_TEXT)
    monkeypatch.setattr(llm, "chat_stream", _CHAT_STREAM)
    monkeypatch.setattr(llm, "_clients", {})
    monkeypatch.setattr(llm.settings, "deepseek_api_key", FAKE_KEY)
    monkeypatch.setattr(llm.settings, "deepseek_base_url", "https://models.example.test/v1")
    monkeypatch.setattr(llm.settings, "deepseek_model", "fake-model")
    monkeypatch.setattr(llm.settings, "llm_timeout_seconds", 12)
    monkeypatch.setattr(llm.settings, "agent_trace_enabled", False)
    monkeypatch.setattr(agent_tracing, "_state", agent_tracing._TracingState())
    monkeypatch.setattr(generation_observation, "current_run", lambda: (
        generation_observation.GenerationRun("fake-user", "parameterized", instance.backend)
        if instance.backend is not None else None
    ))
    # 直接禁用 trace，并逐字段恢复；绝不启动 SDK 默认云端 trace 导出。
    provider = get_trace_provider()
    for name in ("_manual_disabled", "_env_disabled", "_disabled"):
        monkeypatch.setattr(provider, name, getattr(provider, name))
    monkeypatch.setattr(
        provider._multi_processor, "_processors", provider._multi_processor._processors,
    )
    agents.set_tracing_disabled(True)

    real_sync_openai = openai.OpenAI

    def sync_openai(**kwargs):
        assert kwargs["max_retries"] == 0
        http_client = httpx.Client(transport=httpx.MockTransport(instance.respond))
        instance.sync_clients.append(http_client)
        return real_sync_openai(**kwargs, http_client=http_client)

    def async_http_client(**kwargs):
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, context: instance.loop_errors.append(context))
        if loop not in instance.loops:
            instance.loops.append(loop)
        client = httpx.AsyncClient(transport=httpx.MockTransport(instance.respond), **kwargs)
        instance.async_clients.append(client)
        return client

    real_async_openai = openai.AsyncOpenAI

    def async_openai(**kwargs):
        assert kwargs["max_retries"] == 0
        assert kwargs["timeout"] == 12.0
        return real_async_openai(**kwargs)

    monkeypatch.setattr(llm, "OpenAI", sync_openai)
    monkeypatch.setattr(agent_sdk, "DefaultAsyncHttpxClient", async_http_client)
    monkeypatch.setattr(agent_sdk, "AsyncOpenAI", async_openai)
    yield instance
    for client in llm._clients.values():
        client.close()
    instance.assert_clean()


def test_real_agent_runner_model_and_wire_parameters(wire, monkeypatch):
    from agents import OpenAIChatCompletionsModel, Runner

    original_run = Runner.run
    calls = []

    async def run(agent, *args, **kwargs):
        calls.append((agent, kwargs))
        return await original_run(agent, *args, **kwargs)

    monkeypatch.setattr(Runner, "run", run)
    bodies = []
    for backend in ("legacy", "sdk"):
        wire.backend = backend
        wire.replies = [completion(' {"questions": []}\n')]
        assert llm.chat_json(MESSAGES, max_tokens=128, thinking_off=True) == {"questions": []}
        bodies.append(wire.requests[-1])
    assert bodies[0] == bodies[1] == {
        "model": "fake-model", "messages": MESSAGES,
        "response_format": {"type": "json_object"}, "temperature": 0.7,
        "max_tokens": 128, "thinking": {"type": "disabled"},
    }
    assert len(calls) == 1
    agent, kwargs = calls[0]
    assert isinstance(agent.model, OpenAIChatCompletionsModel)
    assert agent.model_settings.retry.max_retries == 0
    assert not agent.tools and not agent.handoffs
    assert agent.output_type is None and agent.instructions is None
    assert kwargs == {
        "input": MESSAGES, "max_turns": 1,
        "error_handlers": {"model_refusal": agent_sdk._legacy_refusal},
    }


@pytest.mark.parametrize("budget,retries,contents", [
    (10, 1, ["{", "{", "{", '{"ok": true}']),
    (None, 1, ["{", '{"ok": true}']),
    (0, 0, ['{"ok": true}']),
    (10, 0, ["{", "{", "{"]),
    (None, 0, ["{"]),
])
def test_json_budgets_feedback_and_call_counts_match_legacy(wire, budget, retries, contents):
    original = copy.deepcopy(MESSAGES)
    bodies = []
    errors = []
    for backend in ("legacy", "sdk"):
        wire.backend = backend
        wire.requests.clear()
        wire.replies = [completion(text) for text in contents]
        if contents[-1] == "{":
            with pytest.raises(llm.LLMError) as error:
                llm.chat_json(MESSAGES, retries=retries, max_tokens=budget)
            errors.append(str(error.value))
        else:
            assert llm.chat_json(MESSAGES, retries=retries, max_tokens=budget) == {"ok": True}
        assert not wire.replies
        bodies.append(copy.deepcopy(wire.requests))
    assert bodies[0] == bodies[1]
    assert len(bodies[1]) == len(contents)
    if budget == 10:
        assert [body["max_tokens"] for body in bodies[1]] == [10, 16, 25, 25][:len(contents)]
    assert [body["temperature"] for body in bodies[1]] == [0.7] + [0.3] * (len(contents) - 1)
    if len(contents) == 4:
        feedback = bodies[1][-1]["messages"]
        assert feedback[:-2] == MESSAGES
        assert feedback[-2] == {"role": "assistant", "content": "{"}
        assert feedback[-1]["role"] == "user"
        assert "无法解析为 JSON" in feedback[-1]["content"]
    assert len(set(errors)) <= 1
    assert MESSAGES == original


@pytest.mark.parametrize("status", [401, 402, 429, 500])
@pytest.mark.parametrize("method", ["chat_json", "chat_text", "chat_stream"])
def test_http_failures_do_not_retry_and_keep_existing_error_boundary(wire, status, method):
    errors = []
    for backend in ("legacy", "sdk"):
        wire.backend = backend
        wire.requests.clear()
        wire.replies = [failure("fake provider failure", status)]
        expected = llm.LLMError if method == "chat_json" else openai.APIStatusError
        with pytest.raises(expected) as error:
            if method == "chat_json":
                llm.chat_json(MESSAGES, retries=4, max_tokens=10)
            else:
                result = getattr(llm, method)(MESSAGES, max_tokens=10)
                if method == "chat_stream":
                    list(result)
        errors.append(str(error.value))
        assert len(wire.requests) == 1
    assert errors[0] == errors[1]


@pytest.mark.parametrize("transport_error", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failures_do_not_retry(wire, transport_error):
    wire.replies = [transport_error("fake network failure")]
    with pytest.raises(llm.LLMError):
        llm.chat_json(MESSAGES, retries=3, max_tokens=10)
    assert len(wire.requests) == 1


@pytest.mark.parametrize("method", ["chat_text", "chat_json", "chat_stream"])
def test_thinking_compatibility_fallback_preserves_parameters(wire, method):
    requests = []
    for backend in ("legacy", "sdk"):
        wire.backend = backend
        wire.requests.clear()
        wire.replies = [failure("Unsupported parameter: thinking")]
        if method == "chat_stream":
            response, stream = streamed(['{"ok": true}'])
            wire.replies.append(response)
            assert list(llm.chat_stream(MESSAGES, max_tokens=18, thinking_off=True)) == [
                '{"ok": true}',
            ]
            assert stream.closed
        else:
            wire.replies.append(completion('{"ok": true}'))
            result = getattr(llm, method)(MESSAGES, max_tokens=18, thinking_off=True)
            assert result == ({"ok": True} if method == "chat_json" else '{"ok": true}')
        assert len(wire.requests) == 2
        first, second = wire.requests
        assert first == {**second, "thinking": {"type": "disabled"}}
        requests.append(copy.deepcopy(wire.requests))
    assert requests[0] == requests[1]


@pytest.mark.parametrize("method", ["chat_text", "chat_json", "chat_stream"])
@pytest.mark.parametrize("thinking_off", [False, True])
def test_only_existing_thinking_predicate_can_add_one_call(wire, method, thinking_off):
    wire.replies = [failure("thinking unavailable"), failure("thinking still unavailable")]
    invocation = getattr(llm, method)
    expected = llm.LLMError if method == "chat_json" else openai.BadRequestError
    with pytest.raises(expected):
        result = invocation(MESSAGES, thinking_off=thinking_off)
        if method == "chat_stream":
            list(result)
    assert len(wire.requests) == (2 if thinking_off else 1)


@pytest.mark.parametrize("text", ["  原样\n\n返回 JSON 文本\t ", "", None])
def test_text_returns_original_content_and_response_format(wire, text):
    wire.replies = [completion(text)]
    assert llm.chat_text(
        MESSAGES, temperature=0.25, max_tokens=31, response_format={"type": "json_object"},
    ) == (text or "")
    assert wire.requests[0]["temperature"] == 0.25
    assert wire.requests[0]["max_tokens"] == 31
    assert wire.requests[0]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("text", [None, "实际 content"])
def test_refusal_does_not_change_content_or_trigger_thinking_retry(wire, text):
    for backend in ("legacy", "sdk"):
        wire.backend = backend
        wire.requests.clear()
        wire.replies = [completion(text, refusal="thinking refusal")]
        assert llm.chat_text(MESSAGES, thinking_off=True) == (text or "")
        assert len(wire.requests) == 1


def test_stream_refusal_is_not_returned_as_text_or_retried(wire):
    stream = TrackedStream([
        event({"role": "assistant"}), event({"refusal": "thinking refusal"}),
        event({}, "stop"), b"data: [DONE]\n\n",
    ])
    wire.replies = [httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=stream,
    )]
    assert list(llm.chat_stream(MESSAGES, thinking_off=True)) == []
    assert len(wire.requests) == 1
    assert stream.closed


@pytest.mark.parametrize("detail", [None, "low", "high", "auto"])
def test_sdk_preserves_message_order_and_image_semantics(wire, detail):
    image = {"url": "data:image/png;base64,dGVzdC1vbmx5"}
    if detail is not None:
        image["detail"] = detail
    messages = MESSAGES + [{"role": "user", "content": [
        {"type": "text", "text": "识别这张合成图片\n保持内容"},
        {"type": "image_url", "image_url": image},
    ]}]
    original = copy.deepcopy(messages)
    wire.replies = [completion("图片结果")]
    assert llm.chat_text(messages) == "图片结果"
    expected = copy.deepcopy(messages)
    expected[-1]["content"][-1]["image_url"].setdefault("detail", "auto")
    assert wire.requests[-1]["messages"] == expected
    assert messages == original


def test_stream_yields_only_text_deltas_and_uses_one_loop(wire, monkeypatch):
    from agents import OpenAIChatCompletionsModel, Runner

    original_run = Runner.run_streamed
    results = []

    def run(agent, *args, **kwargs):
        assert isinstance(agent.model, OpenAIChatCompletionsModel)
        assert kwargs["max_turns"] == 1 and "session" not in kwargs
        result = original_run(agent, *args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(Runner, "run_streamed", run)
    response, stream = streamed(["首段", "", "\n", "末段 "])
    wire.replies = [response]
    assert list(llm.chat_stream(MESSAGES, max_tokens=25, temperature=0.2)) == ["首段", "\n", "末段 "]
    assert stream.closed
    assert len(wire.loops) == 1
    assert len(wire.async_clients) == 1
    assert len(results) == 1 and results[0].run_loop_task.done()
    assert wire.requests == [{
        "model": "fake-model", "messages": MESSAGES,
        "temperature": 0.2, "max_tokens": 25, "stream": True,
    }]
    wire.assert_clean()


def test_stream_early_close_cancels_sdk_and_closes_http_and_loop(wire):
    response, stream = streamed(["首段"], terminal="wait")
    wire.replies = [response]
    iterator = llm.chat_stream(MESSAGES)
    assert next(iterator) == "首段"
    iterator.close()
    assert stream.closed
    wire.assert_clean()
    assert len(wire.requests) == 1


@pytest.mark.parametrize("pieces,prefix", [([], False), (["首段"], True)])
def test_stream_read_errors_never_trigger_thinking_fallback(wire, pieces, prefix):
    response, stream = streamed(pieces, terminal="error", prefix=prefix)
    wire.replies = [response]
    received = []
    with pytest.raises(httpx.ReadError, match="thinking stream failed"):
        for piece in llm.chat_stream(MESSAGES, thinking_off=True):
            received.append(piece)
    assert received == pieces
    assert len(wire.requests) == 1
    assert stream.closed
    wire.assert_clean()


@pytest.mark.parametrize("backend", ["legacy", None])
def test_only_sdk_run_uses_sdk_regardless_of_global_backend(wire, monkeypatch, backend):
    wire.backend = backend
    monkeypatch.setattr(llm.settings, "generation_llm_backend", "sdk", raising=False)
    wire.replies = [completion("legacy")]
    assert llm.chat_text(MESSAGES) == "legacy"
    assert not wire.async_clients
    assert len(wire.sync_clients) == 1


def test_sdk_run_does_not_follow_changed_global_backend(wire, monkeypatch):
    monkeypatch.setattr(llm.settings, "generation_llm_backend", "legacy", raising=False)
    wire.replies = [completion("sdk")]
    assert llm.chat_text(MESSAGES) == "sdk"
    assert len(wire.async_clients) == 1
    assert not wire.sync_clients


def test_explicit_user_key_works_without_default_credentials(wire, monkeypatch):
    monkeypatch.setattr(llm.settings, "deepseek_api_key", "")
    wire.replies = [completion("ok")]
    assert llm.chat_text(MESSAGES, api_key=FAKE_KEY) == "ok"


def test_consecutive_calls_do_not_reuse_closed_loop_or_async_client(wire):
    wire.replies = [completion("one"), completion("two")]
    assert llm.chat_text(MESSAGES) == "one"
    assert llm.chat_text(MESSAGES) == "two"
    assert len(wire.loops) == len(wire.async_clients) == 2
    wire.assert_clean()


def test_standalone_sdk_initializes_tracing_before_model_execution(wire):
    from agents.tracing import get_trace_provider

    from app.services import agent_tracing

    processors = get_trace_provider()._multi_processor
    processors._processors = (object(),)
    wire.replies = [completion("ok")]
    assert llm.chat_text(MESSAGES) == "ok"
    assert agent_tracing.snapshot()["status"] == "disabled"
    assert get_trace_provider()._multi_processor is not processors
    assert not get_trace_provider()._multi_processor._processors


def test_unprepared_sdk_provider_rejects_without_model_request(wire, monkeypatch):
    """执行 provider 无法准备时，拒绝受理而非恢复 SDK 默认云端出口。"""
    from app.services import agent_tracing

    monkeypatch.setattr(agent_tracing, "initialize", lambda: None)
    with pytest.raises(AppError) as error:
        llm.chat_text(MESSAGES)
    assert error.value.status_code == 503
    assert error.value.code == "AGENT_RUNTIME_UNAVAILABLE"
    assert wire.requests == []


@pytest.mark.parametrize("method", ["chat_json", "chat_text", "chat_stream"])
def test_missing_key_keeps_existing_llm_error_without_http_request(wire, monkeypatch, method):
    monkeypatch.setattr(llm.settings, "deepseek_api_key", "")
    with pytest.raises(llm.LLMError, match="DeepSeek API Key 未配置"):
        result = getattr(llm, method)(MESSAGES)
        if method == "chat_stream":
            list(result)
    assert not wire.requests


def test_thread_workers_have_distinct_closed_clients_and_loops(wire):
    wire.replies = [completion("ok"), completion("ok")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: llm.chat_text(MESSAGES), range(2))) == ["ok", "ok"]
    assert len(wire.loops) == len(wire.async_clients) == 2
    wire.assert_clean()


@pytest.mark.parametrize("entrypoint", [agent_sdk.prepare_runtime, agent_sdk.ensure_available])
def test_missing_sdk_has_safe_service_unavailable_error(monkeypatch, entrypoint):
    def missing(name):
        raise ImportError("private dependency installation details")

    monkeypatch.setattr(agent_sdk, "import_module", missing)
    with pytest.raises(AppError) as error:
        entrypoint()
    assert error.value.code == "AGENT_RUNTIME_UNAVAILABLE"
    assert error.value.status_code == 503
    assert "private" not in error.value.message


def test_import_is_lazy_without_sdk_or_runtime_side_effects(monkeypatch):
    import runpy
    import sys

    monkeypatch.setitem(sys.modules, "agents", None)
    namespace = runpy.run_path(agent_sdk.__file__)
    with pytest.raises(AppError) as error:
        namespace["ensure_available"]()
    assert error.value.code == "AGENT_RUNTIME_UNAVAILABLE"

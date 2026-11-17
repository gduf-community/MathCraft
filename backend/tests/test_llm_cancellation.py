"""Real SDK calls over mock HTTP verify cancellation without changing retry semantics."""

import json
from collections.abc import Iterator
from threading import Event

import httpx
import pytest
from openai import OpenAI

from app.schemas.api import GenerateStartBody, TypeCountBody
from app.services import generation
from app.services.generation_cancellation import GenerationCanceled
from app.services.rag import hyde, llm, question_gen

REAL_JSON = llm.chat_json
REAL_TEXT = llm.chat_text
REAL_STREAM = llm.chat_stream
FAKE_KEY = "fake-cancellation-test-key"
MESSAGES = [{"role": "user", "content": "fake prompt"}]


def _check(canceled: Event):
    def check() -> None:
        if canceled.is_set():
            raise GenerationCanceled("fake cancellation")

    return check


@pytest.fixture
def sdk(monkeypatch, fake_models):
    clients = []
    monkeypatch.setattr(llm, "chat_json", REAL_JSON)
    monkeypatch.setattr(llm, "chat_text", REAL_TEXT)
    monkeypatch.setattr(llm, "chat_stream", REAL_STREAM)
    monkeypatch.setattr(llm, "get_platform_llm", lambda: None)
    monkeypatch.setattr(llm, "_thinking_variant_cache", {})
    monkeypatch.setattr(llm, "_thinking_off_cache", {})

    def install(handler):
        client = OpenAI(
            api_key=FAKE_KEY, base_url="https://model.example.test/v1", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        monkeypatch.setattr(llm, "get_client", lambda api_key=None, *, runtime=None: client)

    yield install
    for client in clients:
        client.close()


def _response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{
        "index": 0, "message": {"role": "assistant", "content": content},
        "finish_reason": "stop",
    }]})


@pytest.mark.parametrize("bound", [False, True])
def test_json_budget_and_repair_semantics_are_preserved(sdk, bound):
    calls = []
    canceled = Event()

    def respond(request):
        calls.append(json.loads(request.content))
        return _response('{"answer":' if len(calls) < 4 else '{"answer": "fake answer"}')

    sdk(respond)
    assert llm.chat_json(
        MESSAGES, api_key=FAKE_KEY, max_tokens=10, retries=1,
        cancel_check=_check(canceled) if bound else None,
    ) == {"answer": "fake answer"}
    assert [call["max_tokens"] for call in calls] == [10, 16, 25, 25]
    assert calls[0]["messages"] == MESSAGES
    assert calls[-1]["messages"][1]["content"] == '{"answer":'
    assert "请严格只输出合法 JSON" in calls[-1]["messages"][-1]["content"]


def test_json_cancellation_stops_budget_retry(sdk):
    canceled = Event()
    calls = []

    def respond(request):
        calls.append(request)
        canceled.set()
        return _response('{"answer":')

    sdk(respond)
    with pytest.raises(GenerationCanceled):
        llm.chat_json(MESSAGES, api_key=FAKE_KEY, max_tokens=10, cancel_check=_check(canceled))
    assert len(calls) == 1


@pytest.mark.parametrize("cancel", [False, True])
def test_planning_preserves_json_retry_and_propagates_cancellation(sdk, cancel):
    canceled = Event()
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            if cancel:
                canceled.set()
            return _response('{"points":')
        return _response('{"points": ["first", "second"]}')

    sdk(respond)
    if cancel:
        with pytest.raises(GenerationCanceled):
            question_gen._plan_points(
                "", "填空题", "中", 2, [], FAKE_KEY, cancel_check=_check(canceled),
            )
        assert len(calls) == 1
    else:
        assert question_gen._plan_points(
            "", "填空题", "中", 2, [], FAKE_KEY, cancel_check=_check(canceled),
        ) == ["first", "second"]
        assert [call["max_tokens"] for call in calls] == [800, 1280]


@pytest.mark.parametrize("mode", ["json", "text", "stream"])
def test_thinking_fallback_checks_cancellation_before_second_request(sdk, mode):
    canceled = Event()
    calls = []

    def respond(request):
        calls.append(request)
        canceled.set()
        return httpx.Response(400, json={"error": {"message": "unsupported thinking field"}})

    sdk(respond)
    with pytest.raises(GenerationCanceled):
        if mode == "json":
            llm.chat_json(MESSAGES, api_key=FAKE_KEY, thinking_off=True,
                          cancel_check=_check(canceled))
        elif mode == "text":
            llm.chat_text(MESSAGES, api_key=FAKE_KEY, thinking_off=True,
                          cancel_check=_check(canceled))
        else:
            list(llm.chat_stream(MESSAGES, api_key=FAKE_KEY, thinking_off=True,
                                 cancel_check=_check(canceled)))
    assert len(calls) == 1


@pytest.mark.parametrize("entry", ["direct", "generation"])
@pytest.mark.parametrize("cancel", [False, True])
def test_hyde_thinking_fallback_stops_on_cancellation(sdk, isolated_redis, entry, cancel):
    canceled = Event()
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            if cancel:
                canceled.set()
            return httpx.Response(400, json={"error": {"message": "unsupported thinking field"}})
        return _response("  fake HyDE passage  ")

    sdk(respond)
    body = GenerateStartBody(
        bank_id="fake-bank", document_id="fake-document", scope="导数",
        types=[TypeCountBody(type="blank", count=1)],
    )

    def invoke():
        if entry == "direct":
            return hyde.generate_hyde(body.scope, FAKE_KEY, cancel_check=_check(canceled))
        return generation.get_hyde(
            generation.build_params(body), body, FAKE_KEY, cancel_check=_check(canceled),
        )

    if cancel:
        with pytest.raises(GenerationCanceled):
            invoke()
        assert len(calls) == 1
        assert isolated_redis.dbsize() == 0
    else:
        assert invoke() == "fake HyDE passage"
        assert len(calls) == 2
        assert calls[0]["thinking"] == {"type": "disabled"}
        assert "thinking" not in calls[1]
        assert calls[1]["chat_template_kwargs"] == {"thinking": False}
        if entry == "generation":
            assert invoke() == "fake HyDE passage"
            assert len(calls) == 2


def test_stream_drains_and_closes_before_cancellation_propagates(sdk):
    canceled, drained, closed = Event(), Event(), Event()

    class Stream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            canceled.set()
            for text in ("first", "second"):
                chunk = {"choices": [{"index": 0, "delta": {"content": text}}]}
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            drained.set()
            yield b"data: [DONE]\n\n"

        def close(self) -> None:
            closed.set()

    sdk(lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=Stream(),
    ))
    chunks = llm.chat_stream(MESSAGES, api_key=FAKE_KEY, cancel_check=_check(canceled))
    assert next(chunks) == "first"
    assert next(chunks) == "second"
    with pytest.raises(GenerationCanceled):
        next(chunks)
    assert drained.is_set() and closed.is_set()


def test_hyde_does_not_swallow_cancellation_without_callback(monkeypatch):
    def chat(*args, **kwargs):
        raise GenerationCanceled("fake cancellation")

    monkeypatch.setattr(llm, "chat_text", chat)
    with pytest.raises(GenerationCanceled):
        hyde.generate_hyde("导数", FAKE_KEY)


def test_hyde_without_cancellation_preserves_legacy_model_mock(monkeypatch):
    def chat(messages, api_key, temperature, max_tokens, thinking_off):
        return "  fake HyDE passage  "

    monkeypatch.setattr(llm, "chat_text", chat)
    assert generation.get_cached_hyde(
        "fake-bank", "fake-document", "导数", "中", FAKE_KEY,
    ) == "fake HyDE passage"


def test_hyde_model_failure_still_degrades_to_original_query(monkeypatch):
    def chat(*args, **kwargs):
        raise llm.LLMError("fake model failure")

    monkeypatch.setattr(llm, "chat_text", chat)
    assert generation.get_cached_hyde(
        "fake-bank", "fake-document", "导数", "中", FAKE_KEY, cancel_check=lambda: None,
    ) is None

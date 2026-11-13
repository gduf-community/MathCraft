"""Verify optional tracing at the real OpenAI/httpx boundary with fake services."""
# ruff: noqa: E402 -- Optional telemetry packages must be checked before importing protobufs.
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from threading import Barrier, Event
import time

import httpx
from openai import APITimeoutError, OpenAI
from pydantic import SecretStr
import pytest

pytest.importorskip("opentelemetry.sdk")
pytest.importorskip("opentelemetry.exporter.otlp.proto.common.trace_encoder")
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from app.config import Settings, settings
from app.services import phoenix_tracing as tracing


class CaptureSender:
    """Capture only encoded outgoing telemetry, never model inputs."""

    def __init__(self, *args):
        self.payloads: list[bytes] = []

    def submit(self, payload: bytes) -> bool:
        self.payloads.append(payload)
        return True

    def close(self) -> None:
        pass


@pytest.fixture
def capture(monkeypatch):
    sender = CaptureSender()
    monkeypatch.setattr(tracing, "_Sender", lambda *args: sender)
    assert tracing.configure(settings.model_copy(update={"phoenix_enabled": True}))
    yield sender
    tracing.shutdown()


def spans(sender: CaptureSender):
    return [span for payload in sender.payloads
            for resource in ExportTraceServiceRequest.FromString(payload).resource_spans
            for scope in resource.scope_spans for span in scope.spans]


def attrs(span):
    return {item.key: item.value.string_value or item.value.int_value for item in span.attributes}


def client(handler) -> OpenAI:
    return OpenAI(
        api_key="fake-secret-only-for-tests", base_url="https://fake-model.invalid/v1",
        max_retries=0,
        http_client=tracing.MetadataClient("fake-model", transport=httpx.MockTransport(handler)),
    )


def response(request: httpx.Request) -> httpx.Response:
    assert b"private-input" in request.content
    return httpx.Response(200, json={
        "id": "fake-response", "object": "chat.completion", "created": 1, "model": "fake-model",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "private-output"}}],
    })


def invoke(cli):
    return cli.chat.completions.create(
        model="fake-model", messages=[{"role": "user", "content": "private-input"}],
    ).choices[0].message.content


def test_real_sdk_metadata_no_bodies_headers_or_exception_text(capture):
    with client(response) as cli:
        @tracing.trace_run("conversation")
        def run():
            identifier = tracing.current_run_id()
            assert invoke(cli) == "private-output"
            return identifier

        identifier = run()
    recorded = spans(capture)
    assert len(recorded) == 2
    child, root = recorded
    assert child.parent_span_id == root.span_id
    assert child.trace_id == root.trace_id
    assert all(attrs(item)["mathcraft.run_id"] == identifier for item in recorded)
    assert attrs(child)["http.response.status_code"] == 200
    assert child.end_time_unix_nano >= child.start_time_unix_nano
    encoded = b"".join(capture.payloads)
    assert all(value not in encoded for value in (
        b"private-input", b"private-output", b"fake-secret-only-for-tests",
        b"Authorization", b"fake-model.invalid",
    ))
    assert all(not item.events and not item.status.message for item in recorded)
    assert tracing.current_run_id() is None


def test_parallel_runs_nested_workers_never_cross_link(capture):
    barrier = Barrier(2)
    with client(response) as cli:
        @tracing.trace_run("parameterized")
        def run():
            identifier = tracing.current_run_id()
            barrier.wait(timeout=5)
            with tracing.TracingThreadPoolExecutor(max_workers=2) as pool:
                def nested():
                    with tracing.TracingThreadPoolExecutor(max_workers=2) as children:
                        return list(children.map(lambda _: invoke(cli), range(2)))
                assert all(result == ["private-output"] * 2
                           for result in pool.map(lambda _: nested(), range(2)))
            return identifier

        with ThreadPoolExecutor(max_workers=2) as pool:
            identifiers = list(pool.map(lambda _: run(), range(2)))
    assert len(set(identifiers)) == 2
    recorded = spans(capture)
    roots = {attrs(item)["mathcraft.run_id"]: item for item in recorded if not item.parent_span_id}
    assert len(recorded) == 10
    for item in recorded:
        root = roots[attrs(item)["mathcraft.run_id"]]
        assert root.trace_id == item.trace_id
        assert not item.parent_span_id or item.parent_span_id == root.span_id


class FailingStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b"one"
        raise httpx.ReadError("private-stream-failure")


@pytest.mark.parametrize("mode,code", [
    ("complete", None), ("close", None), ("error", "STREAM_INTERRUPTED"),
])
def test_stream_lifetime_and_early_close(capture, mode, code):
    stream = FailingStream() if mode == "error" else httpx.ByteStream(b"private-output")
    transport = tracing.MetadataClient(
        "fake-model", transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream)),
    )

    @tracing.trace_run("conversation")
    def run():
        res = transport.send(
            httpx.Request("POST", "https://fake.invalid/chat/completions"), stream=True,
        )
        assert spans(capture) == []  # The response headers do not finish a streaming call.
        try:
            if mode == "error":
                with pytest.raises(httpx.ReadError):
                    list(res.stream)
            elif mode == "complete":
                assert b"".join(res.stream) == b"private-output"
        finally:
            res.close()

    run()
    child = spans(capture)[0]
    assert attrs(child).get("error.type") == code
    if mode == "close":
        assert attrs(child)["mathcraft.stream.end"] == "closed"
        assert child.status.code == 0  # UNSET: closing alone cannot prove cancellation.
    assert b"private-stream-failure" not in b"".join(capture.payloads)


def test_provider_error_classification_and_propagation(capture):
    def failing(req):
        raise httpx.ReadTimeout("private-error-secret")

    @tracing.trace_run("conversation")
    def run():
        with client(failing) as cli:
            invoke(cli)

    with pytest.raises(APITimeoutError):
        run()
    assert attrs(spans(capture)[0])["error.type"] == "TIMEOUT"
    assert attrs(spans(capture)[1])["error.type"] == "EXECUTION_ERROR"
    assert b"private-error-secret" not in b"".join(capture.payloads)
    assert tracing.current_run_id() is None


def test_sdk_sse_done_is_not_a_stream_failure(capture):
    chunk = {
        "id": "fake", "object": "chat.completion.chunk", "created": 1,
        "model": "fake-model", "choices": [{"index": 0,
        "delta": {"content": "private-output"}, "finish_reason": None}],
    }
    payload = ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()

    with client(lambda req: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=httpx.ByteStream(payload),
    )) as cli:
        @tracing.trace_run("conversation")
        def run():
            with cli.chat.completions.create(
                model="fake-model", stream=True,
                messages=[{"role": "user", "content": "private-input"}],
            ) as result:
                return "".join(item.choices[0].delta.content or "" for item in result)

        assert run() == "private-output"
    child = spans(capture)[0]
    assert child.status.code != 2
    assert "error.type" not in attrs(child)
    assert b"private-output" not in b"".join(capture.payloads)


def test_model_client_preserves_environment_proxy_and_no_proxy(monkeypatch):
    # Fake transports verify actual routing without contacting a proxy or model.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                 "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://fake-proxy.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "direct-model.invalid")
    observed = []

    def fake_transport(**kwargs):
        proxy = kwargs.get("proxy")

        def respond(request):
            observed.append((request.url.host, str(proxy.url) if proxy else None))
            return httpx.Response(200)

        return httpx.MockTransport(respond)

    monkeypatch.setattr("httpx._client.HTTPTransport", fake_transport)
    with tracing.MetadataClient("fake-model") as cli:
        cli.post("https://remote-model.invalid/chat/completions")
        cli.post("https://direct-model.invalid/chat/completions")
        assert cli.follow_redirects is True
    assert observed == [
        ("remote-model.invalid", "http://fake-proxy.invalid:8080"),
        ("direct-model.invalid", None),
    ]


def test_disabled_and_missing_extra_never_change_business(monkeypatch):
    tracing.shutdown()
    assert not tracing.configure(settings.model_copy(update={"phoenix_enabled": False}))
    with client(response) as cli:
        assert tracing.trace_run("conversation")(lambda: invoke(cli))() == "private-output"

    original = __import__

    def unavailable(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ModuleNotFoundError("missing optional extra")
        return original(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", unavailable)
    assert not tracing.configure(settings.model_copy(update={"phoenix_enabled": True}))
    assert tracing.trace_run("conversation")(lambda: "still-runs")() == "still-runs"


@pytest.mark.parametrize("values", [
    {"phoenix_enabled": False, "phoenix_timeout_seconds": "private-invalid-value"},
    {"phoenix_enabled": True, "phoenix_queue_size": "private-invalid-value"},
    {"phoenix_enabled": "private-invalid-value"},
])
def test_malformed_optional_types_disable_extension_only(values, caplog):
    configured = Settings(**values)
    assert not configured.phoenix_enabled
    assert configured.phoenix_timeout_seconds == 0.5
    assert configured.auth_jwt_secret == settings.auth_jwt_secret
    assert "invalid optional configuration types" in caplog.text
    assert "private-invalid-value" not in caplog.text


def test_optional_fallback_does_not_bypass_core_configuration_validation():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(auth_access_ttl_seconds=-1, phoenix_queue_size="invalid")


@pytest.mark.parametrize("endpoint", [
    "http://remote.invalid/v1/traces", "https://user:fake@fake.invalid/v1/traces",
    "https://fake.invalid/v1/traces?key=fake", "http://127.0.0.1:6017/wrong",
    "http://127.0.0.1:wrong/v1/traces",
])
def test_invalid_endpoint_disables_extension(endpoint):
    assert not tracing.configure(settings.model_copy(update={
        "phoenix_enabled": True, "phoenix_endpoint": endpoint,
    }))


def test_queue_is_bounded_and_never_waits(monkeypatch):
    monkeypatch.setattr(tracing._Sender, "_work", lambda self: None)
    sender = tracing._Sender("http://127.0.0.1:6017/v1/traces", "", 1, 0.1)
    assert sender.submit(b"first")
    assert not sender.submit(b"second")
    assert sender.queue.qsize() == 1
    sender.close()
    assert not sender.submit(b"after-close")


@pytest.mark.parametrize("outcome", ["down", "redirect", "rejected", "partial", "bad"])
def test_export_failure_isolated_no_redirects_or_response_logging(monkeypatch, caplog, outcome):
    real_client = httpx.Client
    observed = Event()
    count = []

    def exporting(request):
        count.append(request)
        observed.set()
        if outcome == "down":
            raise httpx.ConnectError("private-export-error")
        if outcome == "redirect":
            return httpx.Response(307, headers={"Location": "https://untrusted.invalid/"})
        if outcome == "rejected":
            return httpx.Response(401, content=b"private-export-body")
        if outcome == "partial":
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
            res = ExportTraceServiceResponse()
            res.partial_success.rejected_spans = 1
            res.partial_success.error_message = "private-export-body"
            return httpx.Response(200, content=res.SerializeToString())
        return httpx.Response(200, content=b"private-export-body")

    monkeypatch.setattr(tracing.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(exporting), **kwargs,
    ))
    assert tracing.configure(settings.model_copy(update={
        "phoenix_enabled": True, "phoenix_api_key": SecretStr("fake-export-only"),
    }))
    assert tracing.trace_run("conversation")(lambda: "business-result")() == "business-result"
    assert observed.wait(timeout=5)
    deadline = time.monotonic() + 5
    while "Phoenix export failed" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.01)
    tracing.shutdown()
    assert len(count) == 1
    assert "Phoenix export failed" in caplog.text
    assert "private-export" not in caplog.text


def test_real_entrypoints_keep_wrappers_and_signatures():
    for module_name, name in [
        ("app.api.chat", "send_message"),
        ("app.api.generate", "generate_sync"),
        ("app.services.generation", "run_generation_task"),
    ]:
        function = getattr(importlib.import_module(module_name), name)
        assert function.__wrapped__ is not None

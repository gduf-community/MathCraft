"""Optional, metadata-only Phoenix tracing for the existing OpenAI HTTP client.

The provider is private: no global instrumentation, request bodies, exception
messages or user attributes are collected. Export is bounded and best effort.
"""
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from functools import wraps
import logging
from queue import Empty, Full, Queue
import re
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, ParamSpec, TypeVar
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from openai import DefaultHttpxClient

if TYPE_CHECKING:
    from httpx._client import UseClientDefault
    from httpx._types import AuthTypes
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.trace import Span

    from app.config import Settings

logger = logging.getLogger(__name__)
P = ParamSpec("P")
T = TypeVar("T")
_IDENTIFIER = re.compile(r"[a-zA-Z0-9_.:-]{1,100}\Z")


@dataclass(frozen=True)
class _RunContext:
    run_id: str
    entrypoint: str
    span: "Span"


_run: ContextVar[_RunContext | None] = ContextVar("phoenix_run", default=None)


class _Sender:
    """Own one finite export queue and a daemon that never blocks model calls."""

    def __init__(self, endpoint: str, key: str, capacity: int, timeout: float) -> None:
        self.queue: Queue[bytes] = Queue(capacity)
        self.endpoint = endpoint
        self.key = key
        self.timeout = timeout
        self.stop = Event()
        self.thread = Thread(target=self._work, name="phoenix-export", daemon=True)
        self.thread.start()

    def submit(self, payload: bytes) -> bool:
        """Drop rather than wait when export is unavailable or backlogged."""
        if self.stop.is_set() or len(payload) > 64 * 1024:
            return False
        try:
            self.queue.put_nowait(payload)
            return True
        except Full:
            logger.warning("Phoenix export queue full; metadata dropped")
            return False

    def _work(self) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceResponse,
        )
        from google.protobuf.message import DecodeError

        headers = {"Content-Type": "application/x-protobuf"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        # Never use deployment proxy variables or follow redirects with the key.
        with httpx.Client(timeout=self.timeout, trust_env=False, follow_redirects=False) as client:
            while not self.stop.is_set():
                try:
                    payload = self.queue.get(timeout=0.1)
                except Empty:
                    continue
                try:
                    with client.stream(
                        "POST", self.endpoint, content=payload, headers=headers,
                    ) as res:
                        if not 200 <= res.status_code < 300:
                            raise ValueError("EXPORT_REJECTED")
                        body = bytearray()
                        for chunk in res.iter_bytes():
                            body.extend(chunk)
                            if len(body) > 16384 or self.stop.is_set():
                                raise ValueError("EXPORT_RESPONSE_LIMIT")
                        result = ExportTraceServiceResponse.FromString(bytes(body))
                        if result.partial_success.rejected_spans:
                            raise ValueError("EXPORT_PARTIALLY_REJECTED")
                except (httpx.HTTPError, ValueError, DecodeError):
                    logger.warning("Phoenix export failed; metadata dropped")
                finally:
                    self.queue.task_done()

    def close(self) -> None:
        """Stop within a fixed budget; queued metadata is not a durable log."""
        self.stop.set()
        self.thread.join(timeout=2)


@dataclass
class _Runtime:
    provider: "TracerProvider"
    sender: _Sender


_runtime: _Runtime | None = None


def configure(config: "Settings") -> bool:
    """Enable the private provider, or report unavailable without breaking startup."""
    global _runtime
    shutdown()
    if not config.phoenix_enabled:
        return False
    try:
        endpoint = urlsplit(config.phoenix_endpoint)
        port = endpoint.port
    except ValueError:
        logger.warning("Phoenix unavailable: invalid optional tracing endpoint")
        return False
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or (port is not None and not 1 <= port <= 65535)
            or endpoint.path != "/v1/traces"
            or (endpoint.scheme == "http"
                and endpoint.hostname not in {"localhost", "127.0.0.1", "::1"})
            or not _IDENTIFIER.fullmatch(config.phoenix_project)
            or not 1 <= config.phoenix_queue_size <= 4096
            or not 0 < config.phoenix_timeout_seconds <= 2):
        logger.warning("Phoenix unavailable: invalid optional tracing configuration")
        return False
    sender: _Sender | None = None
    try:
        from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            SimpleSpanProcessor, SpanExporter, SpanExportResult,
        )

        sender = _Sender(
            config.phoenix_endpoint, config.phoenix_api_key.get_secret_value(),
            config.phoenix_queue_size, config.phoenix_timeout_seconds,
        )
        export_sender = sender

        class MetadataExporter(SpanExporter):
            def export(self, spans: Sequence["ReadableSpan"]) -> SpanExportResult:
                try:
                    payload = encode_spans(spans).SerializeToString()
                    return (SpanExportResult.SUCCESS if export_sender.submit(payload)
                            else SpanExportResult.FAILURE)
                except Exception:
                    # The optional instrumentation boundary must never affect execution.
                    logger.warning("Phoenix metadata encoding unavailable")
                    return SpanExportResult.FAILURE

            def shutdown(self) -> None:
                export_sender.close()

        provider = TracerProvider(
            resource=Resource({
                "service.name": "mathcraft", "openinference.project.name": config.phoenix_project,
            }),
            shutdown_on_exit=False,
        )
        provider.add_span_processor(SimpleSpanProcessor(MetadataExporter()))
        _runtime = _Runtime(provider, sender)
        return True
    except Exception:
        if sender:
            sender.close()
        logger.warning("Phoenix unavailable: optional tracing initialization failed")
        return False


def shutdown() -> None:
    """Release only the provider owned by this extension."""
    global _runtime
    runtime, _runtime = _runtime, None
    if runtime:
        try:
            runtime.provider.shutdown()
        except Exception:
            logger.warning("Phoenix shutdown incomplete")


def current_run_id() -> str | None:
    """Return the active identifier for future ops_runs integration."""
    context = _run.get()
    return context.run_id if context else None


def _end(span: "Span | None", error: str | None = None, *, incomplete: bool = False) -> None:
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        if error:
            span.set_attribute("error.type", error)
        if incomplete:
            span.set_attribute("mathcraft.stream.end", "closed")
        code = StatusCode.ERROR if error else StatusCode.UNSET if incomplete else StatusCode.OK
        span.set_status(Status(code))
        span.end()
    except Exception:
        logger.warning("Phoenix span completion unavailable")


def trace_run(entrypoint: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Group a current business execution without changing its result or signature."""
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            runtime = _runtime
            if runtime is None or _run.get() is not None:
                return function(*args, **kwargs)
            try:
                run_id = "run_" + uuid4().hex
                span = runtime.provider.get_tracer("mathcraft.phoenix").start_span(
                    "mathcraft." + entrypoint,
                    attributes={"openinference.span.kind": "CHAIN", "mathcraft.run_id": run_id,
                                "mathcraft.entrypoint": entrypoint},
                )
            except Exception:
                logger.warning("Phoenix run tracing unavailable")
                return function(*args, **kwargs)
            token = _run.set(_RunContext(run_id, entrypoint, span))
            error = None
            try:
                return function(*args, **kwargs)
            except BaseException:
                error = "EXECUTION_ERROR"
                raise
            finally:
                _run.reset(token)
                _end(span, error)
        return wrapped
    return decorate


class TracingThreadPoolExecutor(ThreadPoolExecutor):
    """Carry a separate context snapshot to each generation or review worker."""

    def submit(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        return super().submit(copy_context().run, fn, *args, **kwargs)


def _model_span(model: str) -> "Span | None":
    runtime, context = _runtime, _run.get()
    if runtime is None or context is None:
        return None
    try:
        from opentelemetry.trace import set_span_in_context

        return runtime.provider.get_tracer("mathcraft.phoenix").start_span(
            "openai.chat.completions", context=set_span_in_context(context.span),
            attributes={"openinference.span.kind": "LLM", "mathcraft.run_id": context.run_id,
                        "llm.model_name": model if _IDENTIFIER.fullmatch(model) else "unknown"},
        )
    except Exception:
        logger.warning("Phoenix model tracing unavailable")
        return None


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, inner: httpx.SyncByteStream, span: "Span", status: int) -> None:
        self.inner, self.span, self.status = inner, span, status
        self.finished = False
        self.lock = Lock()

    def _finish(self, error: str | None, *, incomplete: bool = False) -> None:
        with self.lock:
            if not self.finished:
                self.finished = True
                _end(self.span, error, incomplete=incomplete)

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self.inner
        except BaseException:
            self._finish("STREAM_INTERRUPTED")
            raise
        else:
            self._finish("HTTP_ERROR" if self.status >= 400 else None)

    def close(self) -> None:
        try:
            self.inner.close()
        finally:
            # SDKs also close healthy SSE responses at [DONE], before HTTP EOF.
            # A transport-level close alone cannot establish success or cancellation.
            error = "HTTP_ERROR" if self.status >= 400 else None
            self._finish(error, incomplete=error is None)


class MetadataClient(DefaultHttpxClient):
    """Observe requests while preserving SDK proxy, redirect and connection defaults."""

    def __init__(self, model: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self.model = model
        super().__init__(transport=transport)

    def send(
        self,
        request: httpx.Request,
        *,
        stream: bool = False,
        auth: "AuthTypes | UseClientDefault | None" = httpx.USE_CLIENT_DEFAULT,
        follow_redirects: "bool | UseClientDefault" = httpx.USE_CLIENT_DEFAULT,
    ) -> httpx.Response:
        """Keep streaming responses open until consumed or explicitly closed."""
        span = (_model_span(self.model) if request.method == "POST"
                and request.url.path.endswith("/chat/completions") else None)
        try:
            response = super().send(
                request, stream=stream, auth=auth, follow_redirects=follow_redirects,
            )
        except BaseException as exc:
            _end(span, "TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "REQUEST_ERROR")
            raise
        if span:
            try:
                span.set_attribute("http.response.status_code", response.status_code)
                if response.is_stream_consumed:
                    _end(span, "HTTP_ERROR" if response.status_code >= 400 else None)
                else:
                    assert isinstance(response.stream, httpx.SyncByteStream)
                    response.stream = _ResponseStream(response.stream, span, response.status_code)
            except Exception:
                _end(span, "TRACING_ERROR")
        return response

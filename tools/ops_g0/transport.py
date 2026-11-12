"""Local-only OTLP export with redaction before a bounded, nonblocking buffer.

This candidate Adapter is used only by the isolated G0 harness. It installs no
business hooks, SQL ledger, periodic heartbeat, dependency monitor or ops route.
"""

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from queue import Empty, Full, Queue
import threading
import time
from urllib.parse import urlsplit

import httpx
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from .redaction import REDACTED, clean_text, sensitive_key


@dataclass
class ExportCounters:
    """Safe operational counts; no bodies, URLs, headers or exception messages."""

    accepted: int = 0
    exported: int = 0
    dropped: int = 0
    failed: int = 0
    attempts: int = 0
    maximum_depth: int = 0
    boundary_errors: int = 0


def _clean_any(value: AnyValue) -> None:
    """Mutate an OTLP AnyValue using its public protobuf fields."""
    kind = value.WhichOneof("value")
    if kind == "string_value":
        value.string_value = clean_text(value.string_value)
    elif kind == "array_value":
        for item in value.array_value.values:
            _clean_any(item)
    elif kind == "kvlist_value":
        _clean_attributes(value.kvlist_value.values)


def _clean_attributes(attributes: Iterable[KeyValue], exclude_body: bool = False) -> None:
    for attribute in attributes:
        body = attribute.key.startswith(("input.", "output.", "llm.input_", "llm.output_"))
        if sensitive_key(attribute.key) or (exclude_body and body):
            attribute.value.Clear()
            attribute.value.string_value = REDACTED
        else:
            _clean_any(attribute.value)


def sanitize_request(request: ExportTraceServiceRequest) -> bytes:
    """Remove credential forms from OTLP resources, spans, events and links."""
    for resource in request.resource_spans:
        _clean_attributes(resource.resource.attributes)
        for scope in resource.scope_spans:
            scope.scope.name = clean_text(scope.scope.name)
            _clean_attributes(scope.scope.attributes)
            for span in scope.spans:
                span.name = clean_text(span.name)
                raw = " ".join(
                    item.value.string_value
                    for item in span.attributes
                    if item.key in {"http.route", "url.path", "http.target"}
                )
                excluded = any(
                    path in raw
                    for path in (
                        "/api/auth",
                        "/api/users/me/model-settings",
                        "/api/users/me/password",
                    )
                )
                _clean_attributes(span.attributes, excluded)
                span.status.message = clean_text(span.status.message)
                for event in span.events:
                    event.name = clean_text(event.name)
                    _clean_attributes(event.attributes, excluded)
                for link in span.links:
                    _clean_attributes(link.attributes)
    return request.SerializeToString()


class LocalExportBuffer:
    """Buffer sanitized OTLP only, with finite attempts and finite shutdown."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        capacity: int = 32,
        max_attempts: int = 2,
        timeout_seconds: float = 0.5,
        capture: Callable[[bytes], None] | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.path != "/v1/traces"
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Only the explicit local OTLP HTTP endpoint is permitted")
        if capacity < 1 or max_attempts not in {1, 2, 3} or not 0 < timeout_seconds <= 2:
            raise ValueError("Invalid bounded-export limits")
        self._endpoint = endpoint
        self._key = api_key
        self._queue: Queue[bytes] = Queue(maxsize=capacity)
        self._attempt_limit = max_attempts
        self._timeout = timeout_seconds
        self._capture = capture
        self._counters = ExportCounters()
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._deadline = float("inf")
        self._worker = threading.Thread(target=self._run, name="ops-g0-local-export", daemon=True)
        self._worker.start()

    def submit(self, request: ExportTraceServiceRequest) -> None:
        """Sanitize before capture or enqueue; never perform HTTP on the caller."""
        payload = sanitize_request(request)
        if len(payload) > 256 * 1024 or self._closing.is_set():
            with self._lock:
                self._counters.dropped += 1
            return
        if self._capture:
            self._capture(payload)
        try:
            self._queue.put_nowait(payload)
        except Full:
            with self._lock:
                self._counters.dropped += 1
            return
        with self._lock:
            self._counters.accepted += 1
            self._counters.maximum_depth = max(self._counters.maximum_depth, self._queue.qsize())

    def snapshot(self) -> dict[str, int]:
        """Expose finite-buffer counters without credentials or raw errors."""
        with self._lock:
            return asdict(self._counters)

    def record_boundary_error(self) -> None:
        """Count a fail-closed encoding/capture error without retaining the raw exception."""
        with self._lock:
            self._counters.boundary_errors += 1
            self._counters.dropped += 1

    def _send(self, client: httpx.Client, payloads: list[bytes]) -> bool:
        batch = ExportTraceServiceRequest()
        for payload in payloads:
            item = ExportTraceServiceRequest.FromString(payload)
            batch.resource_spans.extend(item.resource_spans)
        for attempt in range(self._attempt_limit):
            if time.monotonic() >= self._deadline:
                return False
            with self._lock:
                self._counters.attempts += 1
            try:
                with client.stream(
                    "POST",
                    self._endpoint,
                    content=batch.SerializeToString(),
                    headers={
                        "Content-Type": "application/x-protobuf",
                        "Authorization": "Bearer " + self._key,
                    },
                ) as response:
                    if 200 <= response.status_code < 300:
                        return True
                    if response.status_code not in {408, 429, 500, 502, 503, 504}:
                        return False
            except httpx.HTTPError:
                pass
            if attempt + 1 < self._attempt_limit:
                self._closing.wait(min(0.05 * (attempt + 1), 0.1))
        return False

    def _run(self) -> None:
        with httpx.Client(timeout=self._timeout, trust_env=False) as client:
            while not self._closing.is_set() or not self._queue.empty():
                try:
                    first = self._queue.get(timeout=0.05)
                except Empty:
                    continue
                items = [first]
                while len(items) < 8:
                    try:
                        items.append(self._queue.get_nowait())
                    except Empty:
                        break
                delivered = self._send(client, items)
                with self._lock:
                    if delivered:
                        self._counters.exported += len(items)
                    else:
                        self._counters.failed += len(items)
                for _ in items:
                    self._queue.task_done()

    def flush(self, timeout_seconds: float = 3) -> bool:
        """Wait only when the harness explicitly requests a bounded evidence flush."""
        deadline = time.monotonic() + timeout_seconds
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def close(self, timeout_seconds: float = 2) -> bool:
        """Bound process exit; unfinished exports remain observable failures."""
        self._deadline = time.monotonic() + timeout_seconds
        self._closing.set()
        self._worker.join(timeout_seconds + 0.1)
        return not self._worker.is_alive()


class G0SpanProcessor(SpanProcessor):
    """Bridge SDK-produced OTel spans to the local redacting export buffer."""

    def __init__(self, buffer: LocalExportBuffer) -> None:
        self.buffer = buffer

    def on_end(self, span: ReadableSpan) -> None:
        """Keep observation failures from escaping into the SDK caller."""
        try:
            self.buffer.submit(encode_spans([span]))
        except Exception:
            # This final telemetry boundary must fail closed even for unexpected
            # encoder/capture failures; never log the potentially sensitive exception.
            self.buffer.record_boundary_error()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.buffer.flush(min(timeout_millis / 1000, 3))

    def shutdown(self) -> None:
        self.buffer.close()

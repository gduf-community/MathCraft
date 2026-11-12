"""Local-only OTLP export with redaction before a bounded, nonblocking buffer.

The application and isolated G0 tools share this transport. It installs no
business hooks, SQL ledger, periodic heartbeat, dependency monitor or ops route.
"""

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from queue import Empty, Full, Queue
import threading
import time
from urllib.parse import urlsplit

import httpx
from google.protobuf.message import DecodeError
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from .redaction import REDACTED, clean_text, has_sensitive_route, is_body_key, sensitive_key


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
    rejected_responses: int = 0


def _clean_any(value: AnyValue, exclude_body: bool = False) -> None:
    """Mutate an OTLP AnyValue using its public protobuf fields."""
    kind = value.WhichOneof("value")
    if kind == "string_value":
        value.string_value = clean_text(value.string_value, exclude_body=exclude_body)
    elif kind == "array_value":
        for item in value.array_value.values:
            _clean_any(item, exclude_body)
    elif kind == "kvlist_value":
        _clean_attributes(value.kvlist_value.values, exclude_body)


def _clean_attributes(attributes: Iterable[KeyValue], exclude_body: bool = False) -> None:
    attributes = list(attributes)
    excluded = exclude_body or has_sensitive_route(
        (attribute.key, attribute.value.string_value) for attribute in attributes
    )
    for attribute in attributes:
        if sensitive_key(attribute.key) or (excluded and is_body_key(attribute.key)):
            attribute.value.Clear()
            attribute.value.string_value = REDACTED
        else:
            _clean_any(attribute.value, excluded)


def sanitize_request(request: ExportTraceServiceRequest) -> bytes:
    """Remove credential forms from OTLP resources, spans, events and links."""
    for resource in request.resource_spans:
        _clean_attributes(resource.resource.attributes)
        for scope in resource.scope_spans:
            scope.scope.name = clean_text(scope.scope.name)
            _clean_attributes(scope.scope.attributes)
            for span in scope.spans:
                span.name = clean_text(span.name)
                excluded = has_sensitive_route(
                    (item.key, item.value.string_value) for item in span.attributes
                )
                _clean_attributes(span.attributes, excluded)
                span.status.message = clean_text(span.status.message)
                for event in span.events:
                    event.name = clean_text(event.name)
                    _clean_attributes(event.attributes, excluded)
                for link in span.links:
                    _clean_attributes(link.attributes, excluded)
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
        # Accessing .port performs urllib's numeric/range validation before the
        # worker exists; otherwise httpx.InvalidURL can kill the exporter thread.
        port = parsed.port
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.path != "/v1/traces"
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or (port is not None and port == 0)
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
        self._unavailable = False
        self._deadline = float("inf")
        self._worker = threading.Thread(target=self._run, name="ops-g0-local-export", daemon=True)
        self._worker.start()

    def submit(self, request: ExportTraceServiceRequest) -> None:
        """Sanitize before capture or enqueue; never perform HTTP on the caller."""
        payload = sanitize_request(request)
        if len(payload) > 256 * 1024:
            with self._lock:
                self._counters.dropped += 1
            return
        if self._capture:
            self._capture(payload)
        with self._lock:
            if self._closing.is_set():
                self._counters.dropped += 1
                return
            try:
                self._queue.put_nowait(payload)
            except Full:
                self._counters.dropped += 1
                return
            self._counters.accepted += 1
            self._counters.maximum_depth = max(self._counters.maximum_depth, self._queue.qsize())

    def snapshot(self) -> dict[str, int]:
        """Expose finite-buffer counters without credentials or raw errors."""
        with self._lock:
            result = asdict(self._counters)
            result["unavailable"] = int(self._unavailable)
            result["pending"] = max(0, result["accepted"] - result["exported"] - result["failed"])
            return result

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
                        content = bytearray()
                        for chunk in response.iter_bytes(chunk_size=4096):
                            if len(content) + len(chunk) > 16384:
                                return False
                            content.extend(chunk)
                        try:
                            receipt = ExportTraceServiceResponse.FromString(bytes(content))
                        except DecodeError:
                            return False
                        if receipt.partial_success.rejected_spans:
                            with self._lock:
                                self._counters.rejected_responses += 1
                            # Do not resend partly accepted batches: acceptance is ambiguous.
                            return False
                        return True
                    if response.status_code not in {408, 429, 500, 502, 503, 504}:
                        return False
            except httpx.HTTPError:
                pass
            if attempt + 1 < self._attempt_limit:
                self._closing.wait(min(0.05 * (attempt + 1), 0.1))
        return False

    def _run(self) -> None:
        try:
            self._consume()
        except Exception:
            # Client construction/context entry can fail before sending (for
            # example, unreadable CA files). Stop admission and settle queued
            # items under the same lock used by submit, retaining no raw error.
            with self._lock:
                self._unavailable = True
                self._closing.set()
                self._counters.boundary_errors += 1
                while True:
                    try:
                        self._queue.get_nowait()
                    except Empty:
                        break
                    self._counters.failed += 1
                    self._queue.task_done()

    def _consume(self) -> None:
        """Own the client and consume bounded batches on the exporter thread."""
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
                try:
                    delivered = self._send(client, items)
                except Exception:
                    # Telemetry is an isolation boundary. Preserve finite queue
                    # accounting and the worker after an unexpected client error.
                    self.record_boundary_error()
                    delivered = False
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
        self._deadline = min(self._deadline, time.monotonic() + timeout_seconds)
        self._closing.set()
        self._worker.join(max(0, min(timeout_seconds, self._deadline - time.monotonic())) + 0.1)
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

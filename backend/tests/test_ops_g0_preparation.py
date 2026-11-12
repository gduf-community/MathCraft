"""Independent G0 preparation tests; no app imports or real model requests.

Run with unittest discovery to avoid loading the application's unrelated fixtures.
Optional OTLP tests skip cleanly outside the separately locked preparation environment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
import unittest
from typing import TYPE_CHECKING
from unittest.mock import create_autospec

from tools.ops_g0.redaction import REDACTED, clean_text, clean_value

if TYPE_CHECKING:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    from tools.ops_g0.transport import LocalExportBuffer


class RedactionTests(unittest.TestCase):
    """Preserve useful synthetic content while excluding credential forms."""

    def test_nested_credentials_and_useful_content(self) -> None:
        result = clean_value(
            {
                "request": {
                    "headers": {"Authorization": "Bearer nested-canary", "Cookie": "cookie-canary"},
                    "data": [{"api_key": "key-canary"}, {"password": "password-canary"}],
                },
                "answer": "极限为0",
                "input_tokens": 5,
            }
        )
        text = json.dumps(result, ensure_ascii=False)
        for marker in ("nested-canary", "cookie-canary", "key-canary", "password-canary"):
            self.assertNotIn(marker, text)
        self.assertIn("极限为0", text)
        self.assertEqual(result["input_tokens"], 5)

    def test_url_exception_and_private_key_forms(self) -> None:
        result = clean_text(
            "request failed https://fixture.invalid?api_key=url-canary&x=1 "
            "password=exception-canary Bearer bearer-canary"
        )
        for marker in ("url-canary", "exception-canary", "bearer-canary"):
            self.assertNotIn(marker, result)
        self.assertEqual(
            clean_text("-----BEGIN PRIVATE KEY-----\nkey-canary\n-----END PRIVATE KEY-----"),
            REDACTED,
        )
        self.assertNotIn("url-canary", clean_text("token%3Durl-canary"))

    def test_auth_and_model_settings_bodies_are_excluded(self) -> None:
        for route in ("/api/auth/login/account", "/api/users/me/model-settings"):
            result = clean_value(
                {
                    "route": route,
                    "request": {"arbitrary": "body-canary"},
                    "response": {"arbitrary": "response-canary"},
                }
            )
            self.assertEqual(result["request"], REDACTED)
            self.assertEqual(result["response"], REDACTED)


try:
    OTLP_AVAILABLE = all(
        version(name) == expected
        for name, expected in {
            "openai-agents": "0.20.0",
            "openinference-instrumentation-openai-agents": "2.7.0",
            "opentelemetry-exporter-otlp-proto-http": "1.45.2",
        }.items()
    )
except PackageNotFoundError:
    OTLP_AVAILABLE = False


@unittest.skipUnless(OTLP_AVAILABLE, "Use the isolated tools/ops_g0 dependency environment")
class BufferTests(unittest.TestCase):
    """Exercise bounded exporting with an isolated loopback receiver."""

    def setUp(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.status = 200
        owner = self

        class Handler(BaseHTTPRequestHandler):
            """Receive only synthetic OTLP and return the chosen fault status."""

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                owner.started.set()
                owner.release.wait(2)
                self.send_response(owner.status)
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def request(self) -> ExportTraceServiceRequest:
        """Build a protocol fixture with one nested synthetic credential marker."""
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        request = ExportTraceServiceRequest()
        span = request.resource_spans.add().scope_spans.add().spans.add()
        span.name = "synthetic-span"
        span.trace_id = b"1" * 16
        span.span_id = b"2" * 8
        field = span.attributes.add()
        field.key = "input.value"
        field.value.string_value = '{"password":"buffer-canary","topic":"continuous"}'
        return request

    def buffer(self, **kwargs: object) -> LocalExportBuffer:
        """Connect an isolated exporter only to this test's receiver."""
        from tools.ops_g0.transport import LocalExportBuffer

        endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/traces"
        kwargs.setdefault("max_attempts", 1)
        return LocalExportBuffer(endpoint, "synthetic-test-key", **kwargs)

    def test_redaction_precedes_capture_and_enqueue(self) -> None:
        captured = []
        buffer = self.buffer(capture=captured.append)
        self.release.set()
        buffer.submit(self.request())
        self.assertTrue(buffer.flush(2))
        self.assertTrue(buffer.close(1))
        self.assertEqual(len(captured), 1)
        self.assertNotIn(b"buffer-canary", captured[0])
        self.assertIn(b"continuous", captured[0])
        self.assertEqual(buffer.snapshot()["exported"], 1)

    def test_full_buffer_drops_without_blocking_caller(self) -> None:
        buffer = self.buffer(capacity=1, timeout_seconds=1)
        buffer.submit(self.request())
        self.assertTrue(self.started.wait(2))
        started = time.monotonic()
        for _ in range(64):
            buffer.submit(self.request())
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.5)
        self.assertGreater(buffer.snapshot()["dropped"], 0)
        self.assertLessEqual(buffer.snapshot()["maximum_depth"], 1)
        self.release.set()
        self.assertTrue(buffer.flush(2))
        self.assertTrue(buffer.close(1))

    def test_nonlocal_or_credentialed_endpoint_is_rejected(self) -> None:
        from tools.ops_g0.transport import LocalExportBuffer

        for endpoint in (
            "https://api.openai.com/v1/traces",
            "http://fixture.invalid/v1/traces",
            "http://user:password@127.0.0.1:6016/v1/traces",
            "http://127.0.0.1:6016/v1/traces?token=invalid",
        ):
            with self.assertRaises(ValueError):
                LocalExportBuffer(endpoint, "fake")

    def test_retry_exhaustion_and_recovery_export_new_samples(self) -> None:
        self.release.set()
        self.status = 503
        buffer = self.buffer(max_attempts=2, timeout_seconds=0.2)
        buffer.submit(self.request())
        self.assertTrue(buffer.flush(2))
        self.assertEqual(buffer.snapshot()["attempts"], 2)
        self.assertEqual(buffer.snapshot()["failed"], 1)
        self.status = 200
        buffer.submit(self.request())
        self.assertTrue(buffer.flush(2))
        self.assertTrue(buffer.close(1))
        self.assertEqual(buffer.snapshot()["exported"], 1)
        self.assertEqual(buffer.snapshot()["attempts"], 3)

    def test_timeout_and_shutdown_are_bounded(self) -> None:
        buffer = self.buffer(max_attempts=2, timeout_seconds=0.05)
        buffer.submit(self.request())
        self.assertTrue(self.started.wait(2))
        started = time.monotonic()
        self.assertTrue(buffer.close(0.3))
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(buffer.snapshot()["failed"], 1)
        self.assertLessEqual(buffer.snapshot()["attempts"], 2)

    def test_disconnection_exhausts_finite_attempts(self) -> None:
        from tools.ops_g0.transport import LocalExportBuffer

        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))  # Bound but not listening: deterministic refusal.
            endpoint = f"http://127.0.0.1:{unavailable.getsockname()[1]}/v1/traces"
            buffer = LocalExportBuffer(
                endpoint, "synthetic-key", max_attempts=2, timeout_seconds=0.1
            )
            buffer.submit(self.request())
            self.assertTrue(buffer.flush(2))
            self.assertTrue(buffer.close(0.3))
        self.assertEqual(buffer.snapshot()["attempts"], 2)
        self.assertEqual(buffer.snapshot()["failed"], 1)

    def test_encoding_or_capture_failure_cannot_break_span_caller(self) -> None:
        from opentelemetry.sdk.trace import TracerProvider
        from tools.ops_g0.transport import G0SpanProcessor

        def failed_capture(_payload: bytes) -> None:
            raise RuntimeError("synthetic capture failure")

        buffer = self.buffer(capture=failed_capture)
        provider = TracerProvider()
        provider.add_span_processor(G0SpanProcessor(buffer))
        with provider.get_tracer(__name__).start_as_current_span("synthetic"):
            pass
        self.assertEqual(buffer.snapshot()["boundary_errors"], 1)
        self.assertEqual(buffer.snapshot()["dropped"], 1)
        provider.shutdown()


@unittest.skipUnless(OTLP_AVAILABLE, "Use the isolated tools/ops_g0 dependency environment")
class CleanupBoundaryTests(unittest.TestCase):
    """Check deletion safety and bounded windows without any Phoenix request."""

    def test_business_project_is_rejected_before_any_request(self) -> None:
        from tools.ops_g0.phoenix import Phoenix
        from tools.ops_g0.retention import delete_windows

        client = create_autospec(Phoenix, instance=True)
        now = datetime(2026, 11, 12, tzinfo=UTC)
        with self.assertRaises(ValueError):
            delete_windows(client, "business-project", now - timedelta(days=4), now)
        client.request.assert_not_called()

    def test_cleanup_bounds_work_and_excludes_unexpired_window(self) -> None:
        from tools.ops_g0.phoenix import Phoenix
        from tools.ops_g0.retention import delete_windows

        client = create_autospec(Phoenix, instance=True)
        now = datetime(2026, 11, 12, tzinfo=UTC)
        project = "ops-g0-retention-unittest"
        windows = delete_windows(client, project, now - timedelta(days=30), now)
        self.assertEqual(len(windows), 8)
        self.assertEqual(client.request.call_count, 8)
        for window in windows:
            self.assertLessEqual(
                datetime.fromisoformat(window["end_time"]), now - timedelta(days=3)
            )
        client.request.reset_mock()
        self.assertEqual(delete_windows(client, project, now - timedelta(days=3), now), [])
        client.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()

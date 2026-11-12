"""Independent G0 preparation tests; no app imports or real model requests.

Run with unittest discovery to avoid loading the application's unrelated fixtures.
Optional OTLP tests skip cleanly outside the separately locked preparation environment.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
import unittest
from typing import TYPE_CHECKING
from unittest.mock import create_autospec, patch

from tools.ops_g0.redaction import REDACTED, clean_text, clean_value

# Collection occurs before per-test network guards. Restore only explicitly
# owned numeric-loopback receivers inside BufferTests, preserving all other bans.
_SOCKET_CONNECT = socket.socket.connect
_SOCKET_CREATE_CONNECTION = socket.create_connection

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

    def test_truncated_json_and_quoted_values_do_not_leak_credentials(self) -> None:
        samples = (
            json.dumps({"password": "long-json-canary", "padding": "x" * 5000}),
            '{"password":"partial-json-canary',
            "request failed password='quoted secret canary'",
            "-----BEGIN PRIVATE KEY-----\nprivate-key-canary\n"
            + "x" * 5000
            + "\n-----END PRIVATE KEY-----",
        )
        for sample in samples:
            result = clean_text(sample)
            for marker in (
                "long-json-canary",
                "partial-json-canary",
                "quoted secret canary",
                "private-key-canary",
            ):
                self.assertNotIn(marker, result)

    def test_every_sensitive_field_is_redacted_even_in_truncated_json(self) -> None:
        fields = (
            "api_key",
            "apikey",
            "password",
            "passwd",
            "secret",
            "Authorization",
            "Cookie",
            "Set-Cookie",
            "access_token",
            "refresh_token",
            "token",
            "bearer",
            "private_key",
            "client_secret",
            "api_token",
        )
        for field in fields:
            marker = "long-field-canary-" + field
            result = clean_text(json.dumps({field: marker, "padding": "x" * 5000}))
            self.assertNotIn(marker, result, msg=field)

    def test_truncated_escaped_nested_json_is_redacted_as_a_whole(self) -> None:
        marker = "nested-escaped-canary"
        nested = json.dumps({"api_key": marker})
        sample = json.dumps([{"role": "user", "content": nested + "x" * 5000}])
        self.assertNotIn(marker, clean_text(sample))
        self.assertEqual(clean_text(sample), REDACTED)

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

    def test_nested_sensitive_body_regression(self) -> None:
        marker = "synthetic-nested-body-canary"
        for route in ("/api/auth/login/account", "/api/users/me/model-settings"):
            for value in (
                {"http.route": route, "http.request.body": marker},
                {"url.full": "http://127.0.0.1" + route, "http.response.body": marker},
                {
                    "route": route,
                    "metadata": [{"nested": json.dumps({"request": {"arbitrary": marker}})}],
                },
            ):
                with self.subTest(route=route, value=value):
                    result = clean_text(json.dumps(value))
                    self.assertNotIn(marker, result)

    def test_ordinary_nested_body_is_preserved_regression(self) -> None:
        value = {
            "url.full": "http://127.0.0.1/api/generate",
            "metadata": [{"request": {"topic": "continuous", "api_key": "nested-key-canary"}}],
        }
        result = clean_text(json.dumps(value))
        self.assertIn("continuous", result)
        self.assertNotIn("nested-key-canary", result)


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
class SanitizationTests(unittest.TestCase):
    """Reject sensitive bodies at the serialized OTLP boundary without any network."""

    def test_full_url_sensitive_body_regression(self) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
        from tools.ops_g0.transport import sanitize_request

        for route in (
            "/api/auth/login/account",
            "/api/users/me/model-settings",
            "/api/users/me/password",
        ):
            with self.subTest(route=route):
                request = ExportTraceServiceRequest()
                span = request.resource_spans.add().scope_spans.add().spans.add()
                url = span.attributes.add()
                url.key, url.value.string_value = "url.full", "http://127.0.0.1" + route
                for key in ("http.request.body", "http.response.body"):
                    body = span.attributes.add()
                    body.key, body.value.string_value = key, "synthetic-url-body-canary"
                self.assertNotIn(b"synthetic-url-body-canary", sanitize_request(request))

    def test_nested_json_sensitive_body_regression(self) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
        from tools.ops_g0.transport import sanitize_request

        for inherited in (False, True):
            with self.subTest(inherited=inherited):
                request = ExportTraceServiceRequest()
                span = request.resource_spans.add().scope_spans.add().spans.add()
                metadata = span.attributes.add()
                metadata.key = "metadata"
                nested = {"http.request.body": "synthetic-json-body-canary"}
                if inherited:
                    route = span.attributes.add()
                    route.key, route.value.string_value = "http.route", "/api/auth/login/account"
                else:
                    nested["http.route"] = "/api/auth/login/account"
                metadata.value.string_value = json.dumps({"nested": [nested]})
                self.assertNotIn(b"synthetic-json-body-canary", sanitize_request(request))

    def test_nested_otlp_values_inherit_exclusion_regression(self) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
        from tools.ops_g0.transport import sanitize_request

        request = ExportTraceServiceRequest()
        span = request.resource_spans.add().scope_spans.add().spans.add()
        route = span.attributes.add()
        route.key, route.value.string_value = "url.full", "http://127.0.0.1/api/users/me/password"
        for attributes in (span.attributes, span.events.add().attributes, span.links.add().attributes):
            metadata = attributes.add()
            metadata.key = "metadata"
            nested = metadata.value.array_value.values.add().kvlist_value.values.add()
            nested.key, nested.value.string_value = "http.request.body", "synthetic-otlp-body-canary"
        self.assertNotIn(b"synthetic-otlp-body-canary", sanitize_request(request))


@unittest.skipUnless(OTLP_AVAILABLE, "Use the isolated tools/ops_g0 dependency environment")
class BufferTests(unittest.TestCase):
    """Exercise bounded exporting with an isolated loopback receiver."""

    def setUp(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.status = 200
        self.response_body = b""
        owner = self

        class Handler(BaseHTTPRequestHandler):
            """Receive only synthetic OTLP and return the chosen fault status."""

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                owner.started.set()
                owner.release.wait(2)
                self.send_response(owner.status)
                self.end_headers()
                if owner.response_body:
                    self.wfile.write(owner.response_body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.allowed_ports = {self.server.server_port}

        def allowed(address: tuple) -> None:
            if address[0] != "127.0.0.1" or address[1] not in self.allowed_ports:
                raise AssertionError("Only this test's owned loopback receiver is allowed")

        def connect(instance: socket.socket, address: tuple) -> None:
            allowed(address)
            _SOCKET_CONNECT(instance, address)

        def create_connection(address: tuple, *args: object, **kwargs: object):
            allowed(address)
            return _SOCKET_CREATE_CONNECTION(address, *args, **kwargs)

        for target, attribute, replacement in (
            (socket.socket, "connect", connect),
            (socket, "create_connection", create_connection),
        ):
            guard = patch.object(target, attribute, replacement)
            guard.start()
            self.addCleanup(guard.stop)
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

    def test_sensitive_http_body_attributes_are_excluded(self) -> None:
        captured = []
        buffer = self.buffer(capture=captured.append)
        request = self.request()
        span = request.resource_spans[0].scope_spans[0].spans[0]
        route = span.attributes.add()
        route.key, route.value.string_value = "http.route", "/api/auth/login/account"
        for key in ("http.request.body", "http.response.body", "request", "response", "body"):
            attr = span.attributes.add()
            attr.key, attr.value.string_value = key, "arbitrary-sensitive-body-canary"
        self.release.set()
        buffer.submit(request)
        self.assertTrue(buffer.flush(2))
        self.assertTrue(buffer.close(1))
        self.assertNotIn(b"arbitrary-sensitive-body-canary", captured[0])

    def test_partial_otlp_rejection_is_failed_without_replaying_batch(self) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceResponse,
        )

        receipt = ExportTraceServiceResponse()
        receipt.partial_success.rejected_spans = 1
        receipt.partial_success.error_message = "synthetic response body canary"
        self.response_body = receipt.SerializeToString()
        self.release.set()
        buffer = self.buffer(max_attempts=2)
        buffer.submit(self.request())
        self.assertTrue(buffer.flush(2))
        self.assertTrue(buffer.close(1))
        self.assertEqual(buffer.snapshot()["exported"], 0)
        self.assertEqual(buffer.snapshot()["failed"], 1)
        self.assertEqual(buffer.snapshot()["rejected_responses"], 1)
        self.assertEqual(buffer.snapshot()["attempts"], 1)

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
            "http://127.0.0.1:badport/v1/traces",
            "http://127.0.0.1:65536/v1/traces",
            "http://127.0.0.1:0/v1/traces",
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

    def test_repeated_close_preserves_first_deadline_and_reports_pending(self) -> None:
        buffer = self.buffer(timeout_seconds=1)
        buffer.submit(self.request())
        self.assertTrue(self.started.wait(2))
        self.assertFalse(buffer.close(0.01))
        self.assertEqual(buffer.snapshot()["pending"], 1)
        started = time.monotonic()
        self.assertFalse(buffer.close(1))
        self.assertLess(time.monotonic() - started, 0.3)
        self.release.set()

    def test_disconnection_exhausts_finite_attempts(self) -> None:
        from tools.ops_g0.transport import LocalExportBuffer

        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))  # Bound but not listening: deterministic refusal.
            self.allowed_ports.add(unavailable.getsockname()[1])
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

    def test_unexpected_transport_failure_keeps_worker_and_queue_accounting(self) -> None:
        buffer = self.buffer()
        calls = []

        def send(_client, _items):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("synthetic-client-boundary-failure")
            return True

        with patch.object(buffer, "_send", send):
            buffer.submit(self.request())
            self.assertTrue(buffer.flush(2))
            self.assertEqual(buffer.snapshot()["boundary_errors"], 1)
            self.assertEqual(buffer.snapshot()["failed"], 1)
            self.assertEqual(buffer.snapshot()["pending"], 0)
            buffer.submit(self.request())
            self.assertTrue(buffer.flush(2))
            self.assertEqual(buffer.snapshot()["exported"], 1)
            self.assertTrue(buffer.close(1))

    def test_client_construction_failure_closes_admission_and_settles_queue(self) -> None:
        import httpx

        entered, release = threading.Event(), threading.Event()

        def fail_client(**_kwargs):
            entered.set()
            release.wait(2)
            raise OSError("synthetic-unreadable-ca-file")

        with patch.object(httpx, "Client", fail_client):
            buffer = self.buffer()
            self.assertTrue(entered.wait(2))
            buffer.submit(self.request())
            release.set()
            self.assertTrue(buffer.close(1))
        snapshot = buffer.snapshot()
        self.assertEqual(snapshot["unavailable"], 1)
        self.assertEqual(snapshot["boundary_errors"], 1)
        self.assertEqual(snapshot["failed"], 1)
        self.assertEqual(snapshot["pending"], 0)
        self.assertTrue(buffer.flush(0.1))
        buffer.submit(self.request())
        self.assertEqual(buffer.snapshot()["accepted"], 1)
        self.assertEqual(buffer.snapshot()["dropped"], 1)


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


@unittest.skipUnless(OTLP_AVAILABLE, "Use the isolated tools/ops_g0 dependency environment")
class ExportGuardTests(unittest.TestCase):
    """Intercept both sync and async HTTP before transport or DNS, on Windows too."""

    def test_sync_and_async_nonlocal_http_are_rejected(self) -> None:
        import httpx
        from tools.ops_g0.harness import local_connections_only

        transport = httpx.MockTransport(lambda _request: httpx.Response(200))
        evidence = {"local_connections": 0, "nonlocal_attempts": 0}

        async def async_attempt() -> None:
            async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
                with self.assertRaises(PermissionError):
                    await client.get("https://api.openai.com/v1/traces")

        with local_connections_only(evidence):
            with httpx.Client(transport=transport, trust_env=False) as client:
                with self.assertRaises(PermissionError):
                    client.get("https://api.openai.com/v1/traces")
            asyncio.run(async_attempt())
        self.assertEqual(evidence["nonlocal_attempts"], 2)

    def test_async_redirect_cannot_escape_loopback_guard(self) -> None:
        import httpx
        from tools.ops_g0.harness import local_connections_only

        reached = []
        evidence = {"local_connections": 0, "nonlocal_attempts": 0}

        def redirect(request: httpx.Request) -> httpx.Response:
            reached.append(request.url.host)
            return httpx.Response(302, headers={"Location": "https://fixture.invalid/escape"})

        async def attempt() -> None:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(redirect), trust_env=False, follow_redirects=True
            ) as client:
                with self.assertRaises(PermissionError):
                    await client.get("http://127.0.0.1/start")

        with local_connections_only(evidence):
            asyncio.run(attempt())
        self.assertEqual(reached, ["127.0.0.1"])
        self.assertEqual(evidence["nonlocal_attempts"], 1)

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

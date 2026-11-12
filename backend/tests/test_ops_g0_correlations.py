"""Pure OTLP correlation regressions for the independent G0 evidence checker.

Run with unittest discovery in the isolated preparation environment. No application,
database, Redis, model provider or Phoenix instance is involved.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import json
from typing import TYPE_CHECKING
import unittest

if TYPE_CHECKING:
    from tools.ops_g0.harness import Case


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
class CorrelationTests(unittest.TestCase):
    """Require one complete, acyclic OTel trace for each independent synthetic run."""

    def case(self, label: str, trace_id: bytes) -> Case:
        """Create only in-memory synthetic execution facts."""
        from tools.ops_g0.harness import Case

        return Case(
            run_id="synthetic-run-" + label,
            sdk_trace_id="trace_" + trace_id.hex(),
            user_id="synthetic-user-" + label,
            session_id="synthetic-session-" + label,
            batch_id="synthetic-batch",
            scenario="correlation-fixture",
            outcome="succeeded",
        )

    def payload(self, case: Case, spans: list[tuple[bytes, bytes, bytes]]) -> bytes:
        """Encode (trace ID, span ID, parent ID) with matching synthetic metadata."""
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        request = ExportTraceServiceRequest()
        scope = request.resource_spans.add().scope_spans.add()
        for trace_id, span_id, parent_id in spans:
            span = scope.spans.add()
            span.trace_id, span.span_id, span.parent_span_id = trace_id, span_id, parent_id
            span.name = "synthetic_thread" if parent_id else "synthetic-root"
            for key, value in {
                "user.id": case.user_id,
                "session.id": case.session_id,
                "metadata": json.dumps(
                    {
                        "run_id": case.run_id,
                        "sdk_trace_id": case.sdk_trace_id,
                        "batch_id": case.batch_id,
                        "phase": "synthetic_generate",
                    }
                ),
            }.items():
                attribute = span.attributes.add()
                attribute.key, attribute.value.string_value = key, value
        return request.SerializeToString()

    def test_minimal_root_and_child_are_accepted(self) -> None:
        from tools.ops_g0.harness import inspect_payloads

        trace_id, root_id, child_id = b"1" * 16, b"r" * 8, b"c" * 8
        case = self.case("a", trace_id)
        records = inspect_payloads(
            [self.payload(case, [(trace_id, root_id, b""), (trace_id, child_id, root_id)])],
            [case],
        )
        self.assertEqual(len(records), 2)
        self.assertEqual({record["trace_id"] for record in records}, {trace_id.hex()})

    def test_child_in_another_trace_is_rejected(self) -> None:
        from tools.ops_g0.harness import inspect_payloads

        trace_id, root_id = b"1" * 16, b"r" * 8
        case = self.case("a", trace_id)
        payload = self.payload(case, [(trace_id, root_id, b""), (b"2" * 16, b"c" * 8, root_id)])
        with self.assertRaises(AssertionError):
            inspect_payloads([payload], [case])

    def test_trace_reused_by_two_runs_is_rejected(self) -> None:
        from tools.ops_g0.harness import inspect_payloads

        trace_id = b"1" * 16
        first, second = self.case("a", trace_id), self.case("b", b"2" * 16)
        payloads = [
            self.payload(first, [(trace_id, b"a" * 8, b""), (trace_id, b"b" * 8, b"a" * 8)]),
            self.payload(second, [(trace_id, b"c" * 8, b""), (trace_id, b"d" * 8, b"c" * 8)]),
        ]
        with self.assertRaises(AssertionError):
            inspect_payloads(payloads, [first, second])

    def test_second_root_in_one_run_is_rejected(self) -> None:
        from tools.ops_g0.harness import inspect_payloads

        trace_id, root_id = b"1" * 16, b"r" * 8
        case = self.case("a", trace_id)
        payload = self.payload(
            case,
            [
                (trace_id, root_id, b""),
                (trace_id, b"c" * 8, root_id),
                (trace_id, b"s" * 8, b""),
            ],
        )
        with self.assertRaises(AssertionError):
            inspect_payloads([payload], [case])

    def test_parent_cycle_disconnected_from_root_is_rejected(self) -> None:
        from tools.ops_g0.harness import inspect_payloads

        trace_id = b"1" * 16
        case = self.case("a", trace_id)
        payload = self.payload(
            case,
            [
                (trace_id, b"r" * 8, b""),
                (trace_id, b"a" * 8, b"b" * 8),
                (trace_id, b"b" * 8, b"a" * 8),
            ],
        )
        with self.assertRaises(AssertionError):
            inspect_payloads([payload], [case])


if __name__ == "__main__":
    unittest.main()

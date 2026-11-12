"""OTLP and persisted correlation regressions for the independent G0 evidence checker.

Run with unittest discovery in the isolated preparation environment. No application,
database, Redis, model provider or Phoenix instance is involved.
"""

from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
from dataclasses import asdict, replace
from importlib.metadata import PackageNotFoundError, version
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
import unittest
from unittest.mock import patch

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
    """Require complete traces and matching optional batches for each synthetic run."""

    def case(self, label: str, trace_id: bytes) -> Case:
        """Create only in-memory synthetic execution facts."""
        from tools.ops_g0.harness import Case

        return Case(
            run_id="synthetic-run-" + label,
            sdk_trace_id="trace_" + trace_id.hex(),
            user_id="synthetic-user-" + label,
            session_id="synthetic-session-" + label,
            batch_id="synthetic-batch-" + label,
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

    def change_batch(
        self, payload: bytes, index: int, batch_id: str | None, *, missing: bool = False
    ) -> bytes:
        """Corrupt only one span's batch while preserving its other correlations."""
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        request = ExportTraceServiceRequest.FromString(payload)
        span = request.resource_spans[0].scope_spans[0].spans[index]
        attribute = next(item for item in span.attributes if item.key == "metadata")
        metadata = json.loads(attribute.value.string_value)
        if missing:
            metadata.pop("batch_id")
        else:
            metadata["batch_id"] = batch_id
        attribute.value.string_value = json.dumps(metadata)
        return request.SerializeToString()

    def test_wrong_or_missing_batch_on_root_or_child_is_rejected(self) -> None:
        from tools.ops_g0.harness import inspect_payloads

        trace_id, root_id = b"1" * 16, b"r" * 8
        first, second = self.case("a", trace_id), self.case("b", b"2" * 16)
        first_payload = self.payload(
            first, [(trace_id, root_id, b""), (trace_id, b"c" * 8, root_id)]
        )
        second_payload = self.payload(
            second, [(b"2" * 16, b"s" * 8, b""), (b"2" * 16, b"d" * 8, b"s" * 8)]
        )
        for index in (0, 1):
            for batch_id, missing in ((second.batch_id, False), (None, False), (None, True)):
                with self.subTest(index=index, batch_id=batch_id, missing=missing):
                    corrupted = self.change_batch(first_payload, index, batch_id, missing=missing)
                    with self.assertRaises(AssertionError):
                        inspect_payloads([corrupted, second_payload], [first, second])

    def test_distinct_batches_and_unpersisted_runs_are_accepted(self) -> None:
        from tools.ops_g0.harness import inspect_payloads

        cases = [self.case("a", b"1" * 16), self.case("b", b"2" * 16)]
        cases.extend(
            replace(self.case(label, trace_id), batch_id=None, outcome=outcome)
            for label, trace_id, outcome in (
                ("c", b"3" * 16, "failed"),
                ("d", b"4" * 16, "succeeded"),
            )
        )
        payloads = []
        for index, case in enumerate(cases, 1):
            trace_id, root_id = bytes([index]) * 16, bytes([index]) * 8
            payload = self.payload(
                case, [(trace_id, root_id, b""), (trace_id, bytes([index + 10]) * 8, root_id)]
            )
            if case.batch_id is None:
                payload = self.change_batch(payload, 1, None, missing=True)
            payloads.append(payload)
        self.assertEqual(len(inspect_payloads(payloads, cases)), 8)

    def test_unexpected_batch_for_unpersisted_run_is_rejected(self) -> None:
        from tools.ops_g0.harness import inspect_payloads

        trace_id, root_id = b"1" * 16, b"r" * 8
        case = replace(self.case("a", trace_id), batch_id=None, outcome="failed")
        payload = self.payload(case, [(trace_id, root_id, b"")])
        with self.assertRaises(AssertionError):
            inspect_payloads([self.change_batch(payload, 0, "synthetic-unexpected-batch")], [case])

    def persisted_fixture(self) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Build independent exported evidence and fake persisted root/child records."""
        cases = [self.case("a", b"1" * 16), self.case("b", b"2" * 16)]
        cases.append(replace(self.case("c", b"3" * 16), batch_id=None, outcome="failed"))
        cases.append(replace(self.case("d", b"4" * 16), batch_id=None))
        exported, persisted = [], []
        for index, case in enumerate(cases, 1):
            trace_id, root_id = (bytes([index]) * 16).hex(), (bytes([index]) * 8).hex()
            for span_id, parent_id in ((root_id, ""), ((bytes([index + 10]) * 8).hex(), root_id)):
                exported.append(
                    {
                        "span_id": span_id,
                        "trace_id": trace_id,
                        "parent_id": parent_id,
                        "run_id": case.run_id,
                    }
                )
                attrs = {
                    "metadata.run_id": case.run_id,
                    "metadata.sdk_trace_id": case.sdk_trace_id,
                    "user.id": case.user_id,
                    "session.id": case.session_id,
                }
                if case.batch_id is not None or not parent_id:
                    attrs["metadata.batch_id"] = case.batch_id
                persisted.append(
                    {
                        "context": {"span_id": span_id, "trace_id": trace_id},
                        "parent_id": parent_id or None,
                        "attributes": attrs,
                    }
                )
        return (
            {
                "project": "ops-g0-synthetic-correlations",
                "cases": [asdict(case) for case in cases],
                "spans": exported,
            },
            persisted,
        )

    def run_persisted_verification(
        self, evidence: dict[str, object], persisted: list[dict[str, object]]
    ) -> dict[str, object]:
        """Exercise verify's file-reading entry with temporary files and no real clients."""
        from tools.ops_g0 import verify as verifier

        with TemporaryDirectory(prefix="mathcraft-synthetic-correlations-") as temporary:
            home = Path(temporary)
            directory = home / "evidence-synthetic"
            directory.mkdir()
            (directory / "sdk-evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
            with (
                patch.object(verifier, "HOME", home),
                patch.object(verifier, "Phoenix", autospec=True) as phoenix,
                patch.object(verifier, "get_spans", return_value=persisted) as get_spans,
                patch.object(verifier.httpx, "Client", autospec=True) as http,
            ):
                http.return_value.__enter__.return_value.get.return_value.status_code = 401
                try:
                    result = verifier.verify(directory.name)
                finally:
                    phoenix.return_value.close.assert_called_once_with()
                    get_spans.assert_called_once_with(phoenix.return_value, evidence["project"])
                self.assertEqual(http.return_value.__enter__.return_value.get.call_count, 2)
            self.assertEqual(
                json.loads((directory / "persisted-spans.json").read_text(encoding="utf-8")),
                persisted,
            )
            self.assertEqual(
                json.loads((directory / "phoenix-verification.json").read_text(encoding="utf-8")),
                result,
            )
            return result

    def test_verify_accepts_correct_multirun_batches_and_none(self) -> None:
        evidence, persisted = self.persisted_fixture()
        result = self.run_persisted_verification(evidence, persisted)
        self.assertEqual(result["span_count"], 8)
        self.assertTrue(result["all_root_child_mappings_match"])

    def test_verify_rejects_wrong_or_missing_batch_on_root_or_child(self) -> None:
        for index in (0, 1):
            for batch_id, missing in (("synthetic-batch-b", False), (None, False), (None, True)):
                with self.subTest(index=index, batch_id=batch_id, missing=missing):
                    evidence, persisted = self.persisted_fixture()
                    attrs = persisted[index]["attributes"]
                    if missing:
                        attrs.pop("metadata.batch_id")
                    else:
                        attrs["metadata.batch_id"] = batch_id
                    with self.assertRaises(AssertionError):
                        self.run_persisted_verification(evidence, persisted)

    def test_verify_rejects_unexpected_batch_for_unpersisted_run(self) -> None:
        for index in (4, 5, 6, 7):
            with self.subTest(index=index):
                evidence, persisted = self.persisted_fixture()
                persisted[index]["attributes"]["metadata.batch_id"] = "synthetic-unexpected-batch"
                with self.assertRaises(AssertionError):
                    self.run_persisted_verification(evidence, persisted)

    def test_harness_assigns_distinct_success_batches_and_none_to_failures(self) -> None:
        from tools.ops_g0 import harness

        captured: list[Case] = []

        async def exercise(case: Case) -> Case:
            case.outcome = "failed" if case.scenario.endswith("failure") else "succeeded"
            case.degraded = case.scenario == "degraded"
            captured.append(case)
            return case

        with TemporaryDirectory(prefix="mathcraft-synthetic-batches-") as temporary:
            with ExitStack() as stack:
                stack.enter_context(patch.object(harness, "HOME", Path(temporary)))
                stack.enter_context(patch.object(harness, "Phoenix", autospec=True))
                buffer = stack.enter_context(
                    patch.object(harness, "LocalExportBuffer", autospec=True)
                )
                buffer.return_value.flush.return_value = True
                buffer.return_value.close.return_value = True
                buffer.return_value.snapshot.return_value = {
                    "dropped": 0,
                    "failed": 0,
                    "boundary_errors": 0,
                }
                for name in ("TracerProvider", "G0SpanProcessor", "OpenAIAgentsInstrumentor"):
                    stack.enter_context(patch.object(harness, name, autospec=True))
                stack.enter_context(patch.object(harness, "exercise", new=exercise))
                stack.enter_context(patch.object(harness, "inspect_payloads", return_value=[]))
                stack.enter_context(patch.object(harness, "set_trace_processors"))
                stack.enter_context(
                    patch("sys.argv", ["synthetic-harness", "--label", "synthetic"])
                )
                stack.enter_context(redirect_stdout(StringIO()))
                harness.main()
            successful = [case for case in captured if case.outcome == "succeeded"]
            self.assertEqual(len(successful), 3)
            self.assertTrue(all(case.batch_id is not None for case in successful))
            self.assertEqual(len({case.batch_id for case in successful}), 3)
            failed = [case for case in captured if case.outcome == "failed"]
            self.assertEqual(len(failed), 2)
            self.assertTrue(all(case.batch_id is None for case in failed))

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

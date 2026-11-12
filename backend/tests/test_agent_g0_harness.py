"""Standalone security checks for the optional business G0 CLI.

Use unittest discovery so the app's pytest conftest/autouse fixtures do not run.
These checks exercise import isolation and the independent correlation gate.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.ops_g0.business import Case, GateError, validate_base_url, verify_phoenix


class HarnessSafetyTests(unittest.TestCase):
    """Prevent paid/network destinations, unsafe imports and false trace acceptance."""

    @staticmethod
    def spans() -> list[dict[str, object]]:
        """A root, real execution agent, and its model with safe correlation facts."""
        result = []
        for identifier, parent, kind in (("root", "", "CHAIN"),
                                          ("stage", "root", "CHAIN"),
                                          ("agent", "stage", "AGENT"),
                                          ("model", "agent", "LLM")):
            result.append({"context": {"trace_id": "otel-one", "span_id": identifier},
                           "parent_id": parent, "name": "generation" if identifier == "stage"
                           else "safe", "span_kind": kind,
                           "attributes": {"user.id": "user-one", "metadata": json.dumps({
                               "run_id": "run-one", "owner_user_id": "user-one",
                               "sdk_trace_id": "trace-sdk", "batch_id": None,
                               "session_id": None, "task_id": None,
                               "stage_id": None if identifier == "root" else "stage-one",
                           })}})
        return result

    @staticmethod
    def case() -> Case:
        case = Case("synthetic", "user-one", batch_id="batch-final")
        case.events = [{"run_id": "run-one", "sdk_trace_id": "trace-sdk",
                        "event_type": name, "metadata": {
                            "stage_id": "stage-one", "stage": "generation",
                            "parent_stage_id": None,
                        }} for name in ("stage.started", "stage.ended")]
        return case

    def test_only_numeric_loopback_and_no_old_phoenix(self) -> None:
        self.assertEqual(validate_base_url("http://127.0.0.1:6026"), "http://127.0.0.1:6026")
        for origin in (
            "http://127.0.0.1:6016", "https://api.openai.com", "http://localhost:6026",
            "http://127.0.0.1:6026/v1", "http://secret@127.0.0.1:6026",
            "http://127.0.0.1:6026?token=private", "http://127.0.0.1:6026#fragment",
        ):
            with self.subTest(origin=origin), self.assertRaises(GateError):
                validate_base_url(origin)

    def test_import_has_no_app_config_network_or_file_mutation(self) -> None:
        source = """
import importlib.abc
import importlib.util
import pathlib
import sys
class NoApp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app' or fullname.startswith('app.'):
            raise RuntimeError('app import during harness import')
def audit(event, args):
    if event == 'open':
        path = str(args[0]).replace('\\\\', '/').split('/')[-1]
        if path in {'.env', 'local_secrets.py', 'private.json'}:
            raise RuntimeError('private read during import')
        mode = args[1]
        if isinstance(mode, str) and any(c in mode for c in 'wax+'):
            raise RuntimeError('write during import')
        if isinstance(args[2], int) and args[2] & (64 | 512 | 1024):
            raise RuntimeError('write flags during import')
    if event in {'socket.connect', 'socket.getaddrinfo', 'os.mkdir', 'os.remove', 'os.rename'}:
        raise RuntimeError('side effect during import')
sys.meta_path.insert(0, NoApp())
sys.addaudithook(audit)
spec = importlib.util.spec_from_file_location('g0_safe_import', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert not any(n == 'app' or n.startswith('app.') for n in sys.modules)
"""
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", source, str(root / "tools/ops_g0/business.py")],
            capture_output=True, check=False, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(result.stdout, b"")

    def test_verifier_accepts_unknown_early_batch_and_rejects_cross_owner_or_parent(self) -> None:
        case = self.case()
        self.assertEqual(len(verify_phoenix(self.spans(), [case], [])), 4)
        wrong_owner = self.spans()
        wrong_owner[-1]["attributes"]["user.id"] = "user-two"
        with self.assertRaisesRegex(GateError, "phoenix_account_correlation"):
            verify_phoenix(wrong_owner, [case], [])
        wrong_parent = self.spans()
        wrong_parent[-1]["parent_id"] = "model"
        with self.assertRaisesRegex(GateError, "phoenix_parent_chain"):
            verify_phoenix(wrong_parent, [case], [])
        leaked = self.spans()
        leaked[0]["attributes"]["output.value"] = "private answer"
        with self.assertRaisesRegex(GateError, "phoenix_body_attributes"):
            verify_phoenix(leaked, [case], [])

    def test_root_agent_and_direct_llm_are_not_native_execution_evidence(self) -> None:
        spans = self.spans()
        root, model = spans[0], spans[-1]
        root["span_kind"] = "AGENT"
        model["parent_id"] = "root"
        with self.assertRaisesRegex(GateError, "phoenix_execution_agent_missing"):
            verify_phoenix([root, model], [self.case()], [])

    def test_llm_must_descend_from_nonroot_execution_agent(self) -> None:
        spans = self.spans()
        spans[0]["span_kind"] = "AGENT"
        spans[-1]["parent_id"] = "root"
        with self.assertRaisesRegex(GateError, "phoenix_llm_execution_parent"):
            verify_phoenix(spans, [self.case()], [])

    def test_stage_and_attempt_metadata_join_events_and_native_descendants(self) -> None:
        spans, case = self.spans(), self.case()
        attempt = {"context": {"trace_id": "otel-one", "span_id": "attempt"},
                   "parent_id": "stage", "name": "regeneration.attempt", "span_kind": "CHAIN",
                   "attributes": dict(spans[-1]["attributes"])}
        spans.insert(2, attempt)
        spans[-2]["parent_id"] = "attempt"
        for span in spans[2:]:
            attrs = span["attributes"]
            facts = json.loads(attrs["metadata"])
            facts["attempt_id"] = "attempt-one"
            attrs["metadata"] = json.dumps(facts)
        case.events += [{"run_id": "run-one", "sdk_trace_id": "trace-sdk",
                         "event_type": name, "metadata": {"attempt_id": "attempt-one"}}
                        for name in ("regeneration.started", "regeneration.finished")]
        self.assertEqual(len(verify_phoenix(spans, [case], [])), 5)
        model_facts = json.loads(spans[-1]["attributes"]["metadata"])
        for key, value, code in (("stage_id", "unrelated", "phoenix_stage_correlation"),
                                 ("stage_id", None, "phoenix_native_stage_metadata"),
                                 ("attempt_id", None, "phoenix_attempt_correlation")):
            with self.subTest(key=key, value=value):
                changed = json.loads(json.dumps(spans))
                changed[-1]["attributes"]["metadata"] = json.dumps({**model_facts, key: value})
                with self.assertRaisesRegex(GateError, code):
                    verify_phoenix(changed, [case], [])


if __name__ == "__main__":
    unittest.main()

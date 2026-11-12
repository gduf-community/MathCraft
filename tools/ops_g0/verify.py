"""Verify persisted synthetic Phoenix spans and controlled trace access."""

import argparse
from datetime import UTC, datetime
import json
import time

import httpx

from .environment import HOME
from .harness import CANARIES
from .phoenix import BASE_URL, Phoenix


def get_spans(phoenix: Phoenix, project: str) -> list[dict]:
    """Bound pagination to synthetic projects; never scan business projects."""
    if not project.startswith("ops-g0-") or not project.replace("-", "").isalnum():
        raise ValueError("Only dedicated synthetic project names are permitted")
    spans = []
    cursor = None
    for _ in range(10):
        params = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        page = phoenix.request("GET", f"/v1/projects/{project}/spans", params=params)
        spans.extend(page["data"])
        cursor = page.get("next_cursor")
        if not cursor:
            return spans
    raise RuntimeError("Synthetic project exceeded the bounded verification window")


def verify(directory: str) -> dict:
    """Compare exporter evidence with public API results, including all child spans."""
    path = (HOME / directory).resolve()
    if path.parent != HOME.resolve() or not path.name.startswith("evidence-"):
        raise ValueError("Use a direct evidence directory under the isolated G0 home")
    evidence = json.loads((path / "sdk-evidence.json").read_text(encoding="utf-8"))
    phoenix = Phoenix()
    try:
        expected = {span["span_id"]: span for span in evidence["spans"]}
        deadline = time.monotonic() + 10
        while True:
            spans = get_spans(phoenix, evidence["project"])
            if len(spans) >= len(expected) or time.monotonic() > deadline:
                break
            time.sleep(0.2)
        actual = {span["context"]["span_id"]: span for span in spans}
        if actual.keys() != expected.keys():
            raise AssertionError("Phoenix persisted span set differs from SDK export evidence")
        cases = {case["run_id"]: case for case in evidence["cases"]}
        for identifier, sample in expected.items():
            span = actual[identifier]
            case = cases[sample["run_id"]]
            attrs = span["attributes"]
            if (
                span["context"]["trace_id"] != sample["trace_id"]
                or (span["parent_id"] or "") != sample["parent_id"]
                or attrs.get("metadata.run_id") != case["run_id"]
                or attrs.get("metadata.sdk_trace_id") != case["sdk_trace_id"]
                or attrs.get("metadata.batch_id") != case["batch_id"]
                or attrs.get("user.id") != case["user_id"]
                or attrs.get("session.id") != case["session_id"]
            ):
                raise AssertionError("Phoenix root/child or account/run mapping differs")
        serialized = json.dumps(spans, ensure_ascii=False)
        if any(marker in serialized for marker in CANARIES):
            raise AssertionError("Synthetic credential marker persisted in Phoenix")
        with httpx.Client(base_url=BASE_URL, timeout=3, trust_env=False) as anonymous:
            unauthorized = anonymous.get(f"/v1/projects/{evidence['project']}/spans").status_code
            invalid_key = anonymous.get(
                f"/v1/projects/{evidence['project']}/spans",
                headers={"Authorization": "Bearer synthetic-invalid"},
            ).status_code
        if unauthorized not in {401, 403} or invalid_key not in {401, 403}:
            raise AssertionError("Phoenix span reading was not access-controlled")
        result = {
            "verified_at": datetime.now(UTC).isoformat(),
            "project": evidence["project"],
            "span_count": len(spans),
            "root_count": sum(not span["parent_id"] for span in spans),
            "all_exported_spans_readable": True,
            "all_root_child_mappings_match": True,
            "synthetic_canaries_absent": True,
            "anonymous_status": unauthorized,
            "invalid_key_status": invalid_key,
            "authenticated_status": 200,
            "business_g0": "BLOCKED_EXTERNAL",
        }
        (path / "phoenix-verification.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        # Safe synthetic bodies only, useful for a second reviewer to reproduce correlations.
        (path / "persisted-spans.json").write_text(
            json.dumps(spans, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return result
    finally:
        phoenix.close()


def main() -> None:
    """Verify only an existing independent preparation evidence directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), indent=2))


if __name__ == "__main__":
    main()

"""Prove public REST deletion using only isolated, explicitly synthetic traces.

No application scheduler, private SQL table or business project is accessed.
"""

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import json
import time
from uuid import uuid4

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from .environment import HOME
from .phoenix import Phoenix
from .verify import get_spans

FIELDS = "id name cronExpression rule { ... on TraceRetentionRuleMaxDays { maxDays } }"


@dataclass(frozen=True)
class CleanupPolicy:
    """Target handoff configuration; no scheduler is started by this module."""

    retention_days: int = 3
    interval_hours: int = 24
    window_hours: int = 24
    max_windows_per_invocation: int = 8
    scheduler_owner: str = "乙/M8_AFTER_G0"


POLICY = CleanupPolicy()


def samples(project: str) -> tuple[bytes, dict[str, str]]:
    """Encode OTLP timestamps through its public protocol: four days old plus fresh control."""
    request = ExportTraceServiceRequest()
    resource = request.resource_spans.add()
    attr = resource.resource.attributes.add()
    attr.key, attr.value.string_value = "openinference.project.name", project
    scope = resource.scope_spans.add()
    scope.scope.name = "isolated-g0-retention-fixtures"
    identifiers = {}
    for label, age_days in (("expired", 4), ("unexpired", 0)):
        trace_id = uuid4().bytes
        identifiers[label] = trace_id.hex()
        root_id = uuid4().bytes[:8]
        started = time.time_ns() - age_days * 86400 * 1_000_000_000
        for name, parent in ((label + "-root", b""), (label + "-child", root_id)):
            span = scope.spans.add()
            span.trace_id, span.span_id = trace_id, root_id if not parent else uuid4().bytes[:8]
            span.parent_span_id, span.name = parent, name
            span.start_time_unix_nano, span.end_time_unix_nano = started, started + 1_000_000
            span.status.code = 1
            for key, value in {
                "openinference.span.kind": "CHAIN",
                "input.value": "合成清理样例",
                "metadata.fixture": label,
            }.items():
                attr = span.attributes.add()
                attr.key, attr.value.string_value = key, value
    return request.SerializeToString(), identifiers


def delete_windows(phoenix: Phoenix, project: str, start: datetime, now: datetime) -> list[dict]:
    """Delete finite UTC windows; durable cursor and daily scheduling belong to M8."""
    if not project.startswith("ops-g0-retention-") or not project.replace("-", "").isalnum():
        raise ValueError("Only synthetic retention projects are permitted")
    if start.tzinfo is None or now.tzinfo is None:
        raise ValueError("Cleanup requires explicit timezone-aware timestamps")
    cutoff = now - timedelta(days=POLICY.retention_days)
    results = []
    for _ in range(POLICY.max_windows_per_invocation):
        if start >= cutoff:
            break
        end = min(start + timedelta(hours=POLICY.window_hours), cutoff)
        phoenix.request(
            "DELETE",
            f"/v1/projects/{project}/traces",
            params={
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )
        results.append(
            {"start_time": start.isoformat(), "end_time": end.isoformat(), "status": 204}
        )
        start = end
    return results


def prove(label: str) -> dict:
    """Select one supported REST mechanism; native expiration stays disabled."""
    if not label.replace("-", "").isalnum():
        raise ValueError("Use a synthetic alphanumeric label")
    project = "ops-g0-retention-" + label
    output = HOME / ("retention-" + label + ".json")
    with output.open("x", encoding="utf-8") as handle:
        json.dump({"state": "STARTED", "project": project}, handle)
    phoenix = Phoenix()
    policy = None
    now = datetime.now(UTC)
    evidence = {
        "project": project,
        "mechanism": "APPLICATION_PUBLIC_REST_TIME_WINDOWS",
        "application_scheduler_installed": False,
        "private_tables_accessed": False,
        "policy": asdict(POLICY),
        "native_retention_disabled": False,
        "started_at": now.isoformat(),
        "actual_deletion_verified": False,
    }
    try:
        if phoenix.client.get(f"/v1/projects/{project}").status_code != 404:
            raise ValueError("Existing synthetic project preserved; choose a new label")
        payload, identifiers = samples(project)
        response = phoenix.client.post(
            "/v1/traces",
            content=payload,
            headers={
                "Content-Type": "application/x-protobuf",
                "Authorization": "Bearer " + phoenix.export_key(),
            },
        )
        if not response.is_success:
            raise RuntimeError(f"Synthetic fixture ingestion status {response.status_code}")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                before = get_spans(phoenix, project)
            except RuntimeError:
                before = []
            if len(before) == 4:
                break
            time.sleep(0.2)
        else:
            raise AssertionError("Expired sample and fresh control were not both readable")
        evidence["trace_ids"] = identifiers
        evidence["before"] = [
            {
                "trace_id": span["context"]["trace_id"],
                "name": span["name"],
                "start_time": span["start_time"],
            }
            for span in before
        ]
        project_id = phoenix.request("GET", f"/v1/projects/{project}")["data"]["id"]
        policy = phoenix.graphql(
            "mutation($input:CreateProjectTraceRetentionPolicyInput!) {"
            "createProjectTraceRetentionPolicy(input:$input) {node {" + FIELDS + "}}}",
            {
                "input": {
                    "name": project + "-native-disabled",
                    "cronExpression": "0 0 * * *",
                    "rule": {"maxDays": {"maxDays": 0}},
                    "addProjects": [project_id],
                }
            },
        )["createProjectTraceRetentionPolicy"]["node"]
        if policy["rule"]["maxDays"] != 0:
            raise AssertionError("Native expiration must be disabled to avoid double scheduling")
        evidence["native_retention_disabled"] = True
        evidence["delete_windows"] = delete_windows(phoenix, project, now - timedelta(days=5), now)
        after = get_spans(phoenix, project)
        if len(after) != 2 or {s["context"]["trace_id"] for s in after} != {
            identifiers["unexpired"]
        }:
            raise AssertionError("Expired root/child must disappear; fresh root/child must remain")
        evidence["repeat_windows"] = delete_windows(phoenix, project, now - timedelta(days=5), now)
        repeated = get_spans(phoenix, project)
        if {s["context"]["span_id"] for s in repeated} != {s["context"]["span_id"] for s in after}:
            raise AssertionError("Repeated deletion changed the fresh control")
        evidence.update(
            {
                "actual_deletion_verified": True,
                "repeat_safe": True,
                "after": [{"trace_id": s["context"]["trace_id"], "name": s["name"]} for s in after],
                "deleted_expired_spans": 2,
                "preserved_control_spans": 2,
            }
        )
        return evidence
    finally:
        if policy:
            evidence["native_disabled_policy_readback"] = policy
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        phoenix.close()


def main() -> None:
    """Never accept an arbitrary project or database path for deletion verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    result = prove(args.label)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "project",
                    "actual_deletion_verified",
                    "deleted_expired_spans",
                    "preserved_control_spans",
                    "native_retention_disabled",
                    "repeat_safe",
                    "policy",
                    "application_scheduler_installed",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

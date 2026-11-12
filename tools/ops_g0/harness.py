"""Run only synthetic SDK workflows against the isolated authenticated Phoenix.

This is independent preparation. It cannot certify either real business entry.
"""

import argparse
import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import copy_context
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import socket
import time
from uuid import uuid4

import httpx

from agents import Agent, Runner, function_tool, trace
from agents.exceptions import AgentsException
from agents.items import ModelResponse, TResponseStreamEvent
from agents.models.interface import Model
from agents.tracing import function_span, generation_span, gen_trace_id, set_trace_processors
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openinference.instrumentation import using_attributes
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider

from .environment import HOME
from .phoenix import BASE_URL, Phoenix
from .transport import G0SpanProcessor, LocalExportBuffer

CANARIES = ("g0-nested-credential-canary", "g0-exception-canary", "g0-cookie-canary")


@dataclass
class Case:
    """Authoritative synthetic execution facts, independent of span status."""

    run_id: str
    sdk_trace_id: str
    user_id: str
    session_id: str
    batch_id: str
    scenario: str
    outcome: str = "accepted"
    degraded: bool = False
    tool_calls: int = 0
    thread_context_ok: bool = False
    duration_ms: float = 0


@contextmanager
def local_connections_only(evidence: dict[str, int]) -> Iterator[None]:
    """Guard sync sockets plus SDK HTTPX sync/async requests, including Windows Proactor."""
    original = socket.socket.connect
    # The locked HTTPX 0.28.1 dispatch runs once per redirect hop. Public send()
    # only sees the first URL, which is insufficient for async Windows sockets.
    original_sync = httpx.Client._send_single_request
    original_async = httpx.AsyncClient._send_single_request

    def check_http(request: httpx.Request) -> None:
        if request.url.scheme != "http" or request.url.host not in {"127.0.0.1", "::1"}:
            evidence["nonlocal_attempts"] += 1
            raise PermissionError("Synthetic harness prohibits nonlocal HTTP requests")

    def send_sync(client: httpx.Client, request: httpx.Request, **kwargs: object) -> httpx.Response:
        check_http(request)
        return original_sync(client, request, **kwargs)

    async def send_async(
        client: httpx.AsyncClient, request: httpx.Request, **kwargs: object
    ) -> httpx.Response:
        check_http(request)
        return await original_async(client, request, **kwargs)

    def guarded(connection: socket.socket, address: tuple) -> object:
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            evidence["nonlocal_attempts"] += 1
            raise PermissionError("Synthetic harness prohibits nonlocal connections")
        evidence["local_connections"] += 1
        return original(connection, address)

    socket.socket.connect = guarded
    httpx.Client._send_single_request = send_sync
    httpx.AsyncClient._send_single_request = send_async
    try:
        yield
    finally:
        socket.socket.connect = original
        httpx.Client._send_single_request = original_sync
        httpx.AsyncClient._send_single_request = original_async


class SyntheticModel(Model):
    """An in-process fake model; no model provider or API credential exists here."""

    def __init__(self, case: Case) -> None:
        self.case = case
        self.calls = 0

    async def get_response(self, *, input: object, **_parameters: object) -> ModelResponse:
        """Emit native generation spans, deterministic tool calls, then final text."""
        self.calls += 1
        with generation_span(
            input=[{"role": "user", "content": "合成题目：求1+1，password=" + CANARIES[0]}],
            model="in-process-synthetic-model",
            usage={"input_tokens": 8, "output_tokens": 4},
        ) as span:
            await asyncio.sleep(0.01)
            if self.case.scenario == "model_failure":
                span.set_error({"message": "synthetic model failure token=" + CANARIES[1]})
                raise RuntimeError("synthetic model failure token=" + CANARIES[1])
            if self.calls == 1:
                output = [
                    ResponseFunctionToolCall(
                        type="function_call",
                        name="synthetic_tool",
                        call_id=uuid4().hex,
                        arguments=json.dumps({"slot": slot}),
                    )
                    for slot in (1, 2)
                ]
            else:
                output = [
                    ResponseOutputMessage(
                        id=uuid4().hex,
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[
                            ResponseOutputText(type="output_text", annotations=[], text="1+1=2")
                        ],
                    )
                ]
            span.span_data.output = [{"role": "assistant", "content": "合成输出1+1=2"}]
            return ModelResponse(
                output=output,
                usage=Usage(requests=1, input_tokens=8, output_tokens=4, total_tokens=12),
                response_id=None,
            )

    def stream_response(self, **_parameters: object) -> AsyncIterator[TResponseStreamEvent]:
        """Streaming is deliberately outside this independent preparation harness."""
        raise NotImplementedError("Synthetic preparation uses Runner.run only")


async def exercise(case: Case) -> Case:
    """Run two concurrent tools and explicitly propagate context to worker threads."""
    started = time.perf_counter()

    @function_tool(failure_error_function=None)
    async def synthetic_tool(slot: int) -> str:
        """Compute a synthetic addition in a thread, with explicit context copying."""
        case.tool_calls += 1
        if case.scenario == "tool_failure":
            raise RuntimeError("synthetic tool error password=" + CANARIES[1])
        if case.scenario == "degraded":
            try:
                raise RuntimeError("synthetic caught error token=" + CANARIES[1])
            except RuntimeError:
                case.degraded = True
        context = copy_context()

        def worker() -> str:
            with function_span("synthetic_thread", input=str(slot)) as span:
                span.span_data.output = "1+1=2"
                return "1+1=2"

        result = await asyncio.get_running_loop().run_in_executor(None, context.run, worker)
        case.thread_context_ok = result == "1+1=2"
        return result

    metadata = {
        "run_id": case.run_id,
        "sdk_trace_id": case.sdk_trace_id,
        "batch_id": case.batch_id,
        "phase": "synthetic_generate",
        "scenario": case.scenario,
        "nested": {"api_key": CANARIES[0], "headers": {"Cookie": CANARIES[2]}},
    }
    with using_attributes(user_id=case.user_id, session_id=case.session_id, metadata=metadata):
        with trace(
            "ops-g0-independent",
            trace_id=case.sdk_trace_id,
            group_id=case.session_id,
            metadata=metadata,
        ):
            case.outcome = "running"
            try:
                agent = Agent(
                    name="synthetic-agent",
                    instructions="Use synthetic_tool twice.",
                    model=SyntheticModel(case),
                    tools=[synthetic_tool],
                )
                result = await Runner.run(agent, "合成输入：1+1", max_turns=3)
                if result.final_output != "1+1=2":
                    raise AssertionError("Unexpected synthetic final output")
                case.outcome = "succeeded"
            except (RuntimeError, AgentsException):
                case.outcome = "failed"
    case.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    return case


def inspect_payloads(
    payloads: list[bytes], cases: list[Case], *, require_thread_spans: bool = True
) -> list[dict]:
    """Verify all roots, descendants and thread spans use the expected correlation."""
    records = []
    expected = {case.run_id: case for case in cases}
    for payload in payloads:
        if any(marker.encode() in payload for marker in CANARIES):
            raise AssertionError("Synthetic credential marker survived the export boundary")
        for resource in ExportTraceServiceRequest.FromString(payload).resource_spans:
            for scope in resource.scope_spans:
                for span in scope.spans:
                    attrs = {field.key: field.value.string_value for field in span.attributes}
                    metadata = json.loads(attrs.get("metadata", "{}"))
                    case = expected[metadata["run_id"]]
                    if (
                        attrs.get("user.id") != case.user_id
                        or attrs.get("session.id") != case.session_id
                    ):
                        raise AssertionError("Synthetic account or session context crossed runs")
                    records.append(
                        {
                            "run_id": case.run_id,
                            "trace_id": span.trace_id.hex(),
                            "span_id": span.span_id.hex(),
                            "parent_id": span.parent_span_id.hex(),
                            "name": span.name,
                            "status_code": span.status.code,
                        }
                    )
    trace_owners: dict[str, str] = {}
    for case in cases:
        spans = [item for item in records if item["run_id"] == case.run_id]
        roots = [item for item in spans if not item["parent_id"]]
        ids = {item["span_id"] for item in spans}
        if len(roots) != 1 or any(
            item["parent_id"] not in ids for item in spans if item["parent_id"]
        ):
            raise AssertionError("Incomplete synthetic root/child relationship")
        root = roots[0]
        trace_id = root["trace_id"]
        if {span["trace_id"] for span in spans} != {trace_id}:
            raise AssertionError("A run's child span belongs to a different trace")
        if trace_id in trace_owners:
            raise AssertionError("Different runs reused the same OTel trace")
        trace_owners[trace_id] = case.run_id
        parents = {span["span_id"]: span["parent_id"] for span in spans}
        for span in spans:
            identifier = span["span_id"]
            visited: set[str] = set()
            while identifier != root["span_id"]:
                if identifier in visited or not parents.get(identifier):
                    raise AssertionError("Span ancestry is cyclic or disconnected from the root")
                visited.add(identifier)
                identifier = parents[identifier]
        if (
            require_thread_spans
            and case.outcome == "succeeded"
            and not any(item["name"] == "synthetic_thread" for item in spans)
        ):
            raise AssertionError("Worker-thread span was not correlated")
    return records


def main() -> None:
    """Archive sanitized evidence only; never present the result as full business G0."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()
    if not args.label.replace("-", "").isalnum():
        parser.error("label must be alphanumeric with optional hyphens")
    directory = HOME / ("evidence-" + args.label)
    directory.mkdir(exist_ok=False)
    project = "ops-g0-" + args.label
    payloads: list[bytes] = []

    def capture(payload: bytes) -> None:
        if len(payloads) >= 1000:
            raise RuntimeError("Synthetic evidence capture limit reached")
        payloads.append(payload)

    phoenix = Phoenix()
    buffer = LocalExportBuffer(
        BASE_URL + "/v1/traces", phoenix.export_key(), capacity=64, capture=capture
    )
    provider = TracerProvider(
        resource=Resource.create({"openinference.project.name": project}),
        span_limits=SpanLimits(max_attributes=128, max_events=32, max_attribute_length=4096),
    )
    provider.add_span_processor(G0SpanProcessor(buffer))
    instrumentor = OpenAIAgentsInstrumentor()
    network = {"local_connections": 0, "nonlocal_attempts": 0}
    cases = [
        Case(uuid4().hex, gen_trace_id(), user, session, args.label, scenario)
        for user, session, scenario in (
            ("synthetic-a", "session-a", "success"),
            ("synthetic-b", "session-b", "success"),
            ("synthetic-a", "session-a", "degraded"),
            ("synthetic-b", "session-b", "model_failure"),
            ("synthetic-a", "session-a", "tool_failure"),
        )
    ]

    async def concurrent() -> None:
        await asyncio.gather(*(exercise(case) for case in cases))

    try:
        # Replace before the very first trace. Do not add a second exporter chain.
        instrumentor.instrument(tracer_provider=provider, exclusive_processor=True)
        with local_connections_only(network):
            asyncio.run(concurrent())
            flushed = buffer.flush(3)
            closed = buffer.close(2)
        records = inspect_payloads(payloads, cases)
        expected = ["succeeded", "succeeded", "succeeded", "failed", "failed"]
        if [case.outcome for case in cases] != expected or not cases[2].degraded:
            raise AssertionError("Authoritative synthetic execution matrix did not match")
        evidence = {
            "scope": "INDEPENDENT_PREPARATION_ONLY",
            "business_g0": "BLOCKED_EXTERNAL",
            "project": project,
            "created_at": datetime.now(UTC).isoformat(),
            "cases": [asdict(case) for case in cases],
            "spans": records,
            "network": network,
            "export": buffer.snapshot(),
            "flush_completed": flushed,
            "shutdown_completed": closed,
            "export_limits": {
                "queue_capacity": 64,
                "worker_batch": 8,
                "attempts": 2,
                "request_timeout_seconds": 0.5,
                "payload_max_bytes": 262144,
            },
            "synthetic_canaries_absent": True,
            "default_processors_replaced_before_first_trace": True,
            "real_model_calls": 0,
            "phoenix_persistence_verified": False,
        }
        (directory / "sdk-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for index, payload in enumerate(payloads):
            (directory / f"sanitized-{index:03}.otlp").write_bytes(payload)
        if (
            not flushed
            or not closed
            or network["nonlocal_attempts"]
            or any(buffer.snapshot()[key] for key in ("dropped", "failed", "boundary_errors"))
        ):
            raise AssertionError(
                "Normal SDK evidence export incomplete; preserved counters show the gap"
            )
        print(
            json.dumps(
                {
                    "evidence_directory": str(directory),
                    "project": project,
                    "cases": len(cases),
                    "spans": len(records),
                    "export": buffer.snapshot(),
                    "nonlocal_attempts": network["nonlocal_attempts"],
                    "business_g0": "BLOCKED_EXTERNAL",
                }
            )
        )
    finally:
        buffer.close(2)
        instrumentor.uninstrument()
        # uninstrument restores the old default chain; leave none for process exit.
        set_trace_processors([])
        provider.shutdown()
        phoenix.close()


if __name__ == "__main__":
    main()

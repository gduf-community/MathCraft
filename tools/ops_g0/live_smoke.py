"""Explicit, bounded real-provider acceptance with synthetic input and local tracing.

Never imported by the application or the offline harness. Credentials come only
from environment; no credential value, header or raw exception is archived.
"""

import argparse
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
import json
import logging
import os
import time
from uuid import uuid4

from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, Runner, function_tool, trace
from agents.tracing import gen_trace_id, set_trace_processors
import httpx
from openai import AsyncOpenAI
from openinference.instrumentation import using_attributes
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider

from .environment import HOME
from .harness import CANARIES, Case, inspect_payloads
from .phoenix import BASE_URL, Phoenix
from .transport import G0SpanProcessor, LocalExportBuffer
from .verify import verify


class ModelTransport(httpx.AsyncBaseTransport):
    """Allow three paid requests to exactly one known provider path, with no redirects."""

    def __init__(self, model: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.model = model
        self.calls: list[dict] = []
        self._transport = transport or httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Enforce the request budget before sending credentials or input."""
        if (
            request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != "api.deepseek.com"
            or request.url.port not in {443, None}
            or request.url.path not in {"/chat/completions", "/v1/chat/completions"}
            or request.url.query
            or request.url.userinfo
        ):
            raise PermissionError(
                "Only the explicitly configured DeepSeek model endpoint is allowed"
            )
        body = json.loads(request.content)
        if body.get("model") != self.model or not 1 <= body.get("max_tokens", 0) <= 128:
            raise PermissionError("The model name and output budget must match the acceptance plan")
        if len(self.calls) >= 3:
            raise PermissionError("The real-model acceptance request budget was exhausted")
        record = {
            "host": request.url.host,
            "path": request.url.path,
            "model": self.model,
            "stream": body.get("stream", False),
            "max_tokens": body["max_tokens"],
        }
        self.calls.append(record)
        started = time.perf_counter()
        try:
            response = await self._transport.handle_async_request(request)
            record["status"] = response.status_code
            return response
        finally:
            record["headers_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)

    async def aclose(self) -> None:
        """Close only this smoke test's model connections."""
        await self._transport.aclose()


@contextmanager
def provider_requests_only(
    model_client: httpx.AsyncClient, evidence: dict[str, int]
) -> Iterator[None]:
    """Guard SDK HTTPX traffic; the sole nonlocal client has its own path/budget transport."""
    original_sync = httpx.Client._send_single_request
    original_async = httpx.AsyncClient._send_single_request

    def local(request: httpx.Request) -> bool:
        return request.url.scheme == "http" and request.url.host in {"127.0.0.1", "::1"}

    def sync_send(client: httpx.Client, request: httpx.Request, **kwargs: object) -> httpx.Response:
        if not local(request):
            evidence["unexpected_http_requests"] += 1
            raise PermissionError("Nonlocal tracing export is prohibited")
        return original_sync(client, request, **kwargs)

    async def async_send(
        client: httpx.AsyncClient, request: httpx.Request, **kwargs: object
    ) -> httpx.Response:
        if client is not model_client and not local(request):
            evidence["unexpected_http_requests"] += 1
            raise PermissionError("Only the budgeted model client may send nonlocal requests")
        return await original_async(client, request, **kwargs)

    httpx.Client._send_single_request, httpx.AsyncClient._send_single_request = (
        sync_send,
        async_send,
    )
    try:
        yield
    finally:
        httpx.Client._send_single_request, httpx.AsyncClient._send_single_request = (
            original_sync,
            original_async,
        )


async def run_cases(model: OpenAIChatCompletionsModel, label: str) -> tuple[list[Case], list[dict]]:
    """Use one real call each for text, tool invocation and streaming; no user data."""
    cases, results = [], []
    for scenario in ("text", "tool", "stream"):
        case = Case(
            uuid4().hex,
            gen_trace_id(),
            "synthetic-live-user",
            "synthetic-live-session",
            label,
            "live_" + scenario,
        )
        cases.append(case)
        tool_invocations = []

        @function_tool
        def add_numbers(a: int, b: int) -> str:
            """Add two integers for a synthetic acceptance example."""
            tool_invocations.append((a, b))
            return str(a + b)

        options = ModelSettings(
            temperature=0, max_tokens=128, extra_body={"thinking": {"type": "disabled"}}
        )
        if scenario == "tool":
            options.tool_choice = "required"
        agent = Agent(
            name="real-provider-" + scenario,
            model=model,
            instructions="This is a synthetic integration test. Follow the requested format.",
            model_settings=options,
            tools=[add_numbers] if scenario == "tool" else [],
            tool_use_behavior="stop_on_first_tool",
        )
        prompt = (
            "Call add_numbers once with a=17 and b=25."
            if scenario == "tool"
            else "Compute 17+25. Output only the integer 42, without explanations."
        )
        metadata = {
            "run_id": case.run_id,
            "sdk_trace_id": case.sdk_trace_id,
            "batch_id": label,
            "phase": "live_acceptance",
            "scenario": scenario,
            "nested": {"api_key": CANARIES[0]},
        }
        started = time.perf_counter()
        with using_attributes(user_id=case.user_id, session_id=case.session_id, metadata=metadata):
            with trace("ops-g0-live-smoke", trace_id=case.sdk_trace_id, group_id=case.session_id):
                case.outcome = "running"
                if scenario == "stream":
                    result = Runner.run_streamed(agent, prompt, max_turns=1)
                    event_count = 0
                    async for _event in result.stream_events():
                        event_count += 1
                else:
                    result = await Runner.run(agent, prompt, max_turns=1)
                    event_count = 0
                if str(result.final_output).strip() != "42":
                    raise AssertionError("Real model did not return the expected synthetic answer")
                if scenario == "tool" and tool_invocations != [(17, 25)]:
                    raise AssertionError("The real model did not invoke the expected local tool")
                if scenario == "stream" and event_count < 1:
                    raise AssertionError("The real streaming interface emitted no events")
                case.outcome = "succeeded"
                case.tool_calls = len(tool_invocations)
        case.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        usage = result.context_wrapper.usage
        if usage.requests != 1 or usage.total_tokens < 1:
            raise AssertionError("Real provider usage was not reported")
        results.append(
            {
                "scenario": scenario,
                "answer": "42",
                "tool_calls": case.tool_calls,
                "stream_events": event_count,
                "requests": usage.requests,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "duration_ms": case.duration_ms,
            }
        )
    return cases, results


def main() -> None:
    """Require deliberate opt-in; leave offline tests and application behavior unchanged."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-model", action="store_true")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not args.allow_real_model:
        parser.error("Real model acceptance must be explicitly requested")
    if not args.label.replace("-", "").isalnum():
        parser.error("Use an alphanumeric label")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    if not key:
        parser.error("Configure DEEPSEEK_API_KEY in the invoking process without printing it")
    if base.rstrip("/") not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
        parser.error(
            "This acceptance tool is restricted to the configured official DeepSeek endpoint"
        )
    directory = HOME / ("evidence-" + args.label)
    directory.mkdir(exist_ok=False)
    project = "ops-g0-" + args.label
    payloads: list[bytes] = []

    def capture(payload: bytes) -> None:
        if key.encode() in payload or any(marker.encode() in payload for marker in CANARIES):
            raise ValueError("Credential marker reached the capture boundary; payload discarded")
        if len(payloads) >= 1000:
            raise ValueError("Bounded evidence capture exhausted")
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
    transport = ModelTransport(model_name)
    network = {"unexpected_http_requests": 0}
    report = {
        "scope": "REAL_PROVIDER_INDEPENDENT_SMOKE",
        "business_g0": "BLOCKED_EXTERNAL",
        "project": project,
        "created_at": datetime.now(UTC).isoformat(),
        "passed": False,
    }
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)  # Provider exceptions must never dump headers or bodies.

    async def execute() -> tuple[list[Case], list[dict]]:
        async with httpx.AsyncClient(
            transport=transport, trust_env=False, timeout=45, follow_redirects=False
        ) as http_client:
            async with AsyncOpenAI(
                api_key=key, base_url=base, max_retries=0, http_client=http_client
            ) as client:
                real_model = OpenAIChatCompletionsModel(model=model_name, openai_client=client)
                with provider_requests_only(http_client, network):
                    return await asyncio.wait_for(run_cases(real_model, args.label), timeout=120)

    try:
        instrumentor.instrument(tracer_provider=provider, exclusive_processor=True)
        cases, outcomes = asyncio.run(execute())
        flushed, closed = buffer.flush(3), buffer.close(2)
        records = inspect_payloads(payloads, cases, require_thread_spans=False)
        if (
            not flushed
            or not closed
            or network["unexpected_http_requests"]
            or any(buffer.snapshot()[field] for field in ("failed", "dropped", "boundary_errors"))
        ):
            raise AssertionError("Real-provider tracing evidence export was incomplete")
        evidence = {
            "scope": report["scope"],
            "business_g0": "BLOCKED_EXTERNAL",
            "project": project,
            "cases": [asdict(case) for case in cases],
            "spans": records,
            "network": network,
            "export": buffer.snapshot(),
            "real_model_calls": len(transport.calls),
            "phoenix_persistence_verified": False,
        }
        (directory / "sdk-evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        for index, payload in enumerate(payloads):
            (directory / f"sanitized-{index:03}.otlp").write_bytes(payload)
        verification = verify(directory.name)
        report.update(
            {
                "passed": True,
                "model": model_name,
                "outcomes": outcomes,
                "provider_calls": transport.calls,
                "export": buffer.snapshot(),
                "network": network,
                "persistence": verification,
            }
        )
    except Exception as error:
        report.update(
            {
                "error_type": type(error).__name__,
                "provider_calls": transport.calls,
                "export": buffer.snapshot(),
                "network": network,
            }
        )
        print(
            json.dumps(
                {
                    "passed": False,
                    "error_type": type(error).__name__,
                    "calls": len(transport.calls),
                    "evidence_directory": str(directory),
                }
            )
        )
        raise SystemExit(1) from None
    finally:
        buffer.close(2)
        instrumentor.uninstrument()
        set_trace_processors([])
        provider.shutdown()
        phoenix.close()
        logging.disable(previous_logging)
        (directory / "real-model-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "passed": True,
                "real_model_calls": len(transport.calls),
                "span_count": len(records),
                "model": model_name,
                "evidence_directory": str(directory),
                "business_g0": "BLOCKED_EXTERNAL",
            }
        )
    )


if __name__ == "__main__":
    main()

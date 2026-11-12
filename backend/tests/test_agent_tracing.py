"""真实 SDK/OI span 经生产白名单进入内存假传输，不连接服务。"""

from dataclasses import dataclass

from app.config import settings
from app.services import agent_tracing


@dataclass
class TraceRun:
    run_id: str = "run_test"
    owner_user_id: str = "user_test"
    entrypoint: str = "parameterized"
    session_id: str | None = None
    task_id: str | None = "task_test"
    batch_id: str | None = None
    sdk_trace_id: str = "trace_" + "a" * 32
    backend: str = "sdk"


def test_sdk_export_excludes_content_and_exceptions(monkeypatch):
    """不能仅依赖凭据正则；任意正文及原异常均不可进入生产导出缓冲。"""
    from agents.tracing import generation_span

    from app.services.agent_telemetry import transport

    captured = []

    class MemoryBuffer:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, request):
            captured.append(request)

        def snapshot(self):
            return {"accepted": len(captured)}

        def record_boundary_error(self):
            raise AssertionError("Unexpected telemetry error")

        def flush(self, timeout_seconds=3):
            return True

        def close(self, timeout_seconds=2):
            return True

    agent_tracing.shutdown()
    monkeypatch.setattr(transport, "LocalExportBuffer", MemoryBuffer)
    monkeypatch.setattr(settings, "agent_trace_enabled", True)
    monkeypatch.setattr(settings, "agent_trace_api_key", "fake-local-export-key")
    try:
        with agent_tracing.run_trace(TraceRun()):
            with agent_tracing.stage_span("generation.test", {
                "stage_id": "stage_test", "attempt_id": "attempt_test",
            }), generation_span(
                input=[{"role": "user", "content": "arbitrary-private-input-canary"}],
                output=[{"role": "assistant", "content": "arbitrary-private-output-canary"}],
                model="fake-model",
            ) as span:
                span.set_error({
                    "message": "arbitrary-private-error-canary", "data": {},
                })
        assert agent_tracing.flush()
        wire = b"".join(request.SerializeToString() for request in captured)
        assert b"arbitrary-private-" not in wire
        assert b"run_test" in wire
        assert b"fake-model" in wire
        assert b"stage_test" in wire and b"attempt_test" in wire
        spans = [
            span
            for request in captured
            for resource in request.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
        ]
        assert len([span for span in spans if not span.parent_span_id]) == 1
        assert len({span.trace_id for span in spans}) == 1
        for span in spans:
            attrs = {item.key: item.value.string_value for item in span.attributes}
            if attrs.get("openinference.span.kind") == "LLM":
                assert "stage_test" in attrs["metadata"]
                assert "attempt_test" in attrs["metadata"]
    finally:
        agent_tracing.shutdown()


def test_exporter_failure_does_not_fail_business(monkeypatch):
    """初始化故障可观测，同时保留业务异常及业务正常结果。"""
    agent_tracing.shutdown()
    monkeypatch.setattr(settings, "agent_trace_enabled", True)
    monkeypatch.setattr(settings, "agent_trace_api_key", "fake-local-export-key")

    def fail():
        raise RuntimeError("private-error-must-not-be-logged")

    monkeypatch.setattr(agent_tracing, "_initialize_exporter", fail)
    try:
        with agent_tracing.run_trace(TraceRun()):
            value = "business-result"
        assert value == "business-result"
        assert agent_tracing.snapshot() == {
            "status": "unavailable", "initialization_errors": 1,
        }
        import pytest

        with pytest.raises(ValueError, match="business-error"):
            with agent_tracing.run_trace(TraceRun()):
                raise ValueError("business-error")
    finally:
        agent_tracing.shutdown()


def test_partial_exporter_initialization_releases_worker(monkeypatch):
    """安装中途失败也必须关闭已经创建的导出资源，禁止泄漏后台线程。"""
    agent_tracing.shutdown()
    monkeypatch.setattr(settings, "agent_trace_enabled", True)
    monkeypatch.setattr(settings, "agent_trace_api_key", "fake-local-export-key")
    closed = []

    class PartialBuffer:
        def close(self, timeout_seconds):
            closed.append(timeout_seconds)

    def fail_after_buffer():
        agent_tracing._state.buffer = PartialBuffer()
        raise RuntimeError("synthetic-instrumentor-install-failure")

    monkeypatch.setattr(agent_tracing, "_initialize_exporter", fail_after_buffer)
    try:
        with agent_tracing.run_trace(TraceRun()):
            pass
        assert closed == [2]
        assert agent_tracing._state.buffer is None
        assert agent_tracing.snapshot()["status"] == "unavailable"
    finally:
        agent_tracing.shutdown()


def test_startup_recovery_failure_still_closes_tracing(monkeypatch):
    """启动尚未到 yield 就失败时，追踪生命周期仍必须成对结束。"""
    import pytest
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import rag_settings

    lifecycle = []
    monkeypatch.setattr(agent_tracing, "initialize", lambda: lifecycle.append("opened"))
    monkeypatch.setattr(agent_tracing, "shutdown", lambda: lifecycle.append("closed"))

    def fail():
        raise RuntimeError("synthetic-startup-recovery-failure")

    monkeypatch.setattr(rag_settings, "recover_interrupted_rebuild", fail)
    with pytest.raises(RuntimeError, match="synthetic-startup-recovery-failure"):
        with TestClient(app):
            pytest.fail("Startup failure must remain visible")
    assert lifecycle == ["opened", "closed"]

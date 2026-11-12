"""SDK tracing 生命周期、本地单出口及不影响业务的有界观测。"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import importlib.util
import logging
import threading
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agents.tracing import TraceProvider
    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
    from opentelemetry.sdk.trace import TracerProvider

    from app.services.agent_telemetry.transport import LocalExportBuffer

logger = logging.getLogger(__name__)


class TraceRun(Protocol):
    """追踪层只消费运行标识，不读取模型凭据或题目内容。"""

    run_id: str
    owner_user_id: str
    entrypoint: str
    session_id: str | None
    task_id: str | None
    batch_id: str | None
    sdk_trace_id: str
    backend: str


@dataclass
class _TracingState:
    initialized: bool = False
    status: str = "not_initialized"
    buffer: "LocalExportBuffer | None" = None
    provider: "TracerProvider | None" = None
    instrumentor: "OpenAIAgentsInstrumentor | None" = None
    boundary_errors: int = 0
    sdk_provider: "TraceProvider | None" = None


_state = _TracingState()
_lock = threading.RLock()
_span_metadata: ContextVar[Mapping[str, object]] = ContextVar("agent_span_metadata", default={})


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _metadata(run: TraceRun) -> dict[str, str | None]:
    return {
        "run_id": run.run_id,
        "sdk_trace_id": run.sdk_trace_id,
        "entrypoint": run.entrypoint,
        "owner_user_id": run.owner_user_id,
        "session_id": run.session_id,
        "task_id": run.task_id,
        "batch_id": run.batch_id,
    }


def initialize() -> None:
    """首次 trace 前移除 SDK 默认出口；缺少可选依赖不阻止应用启动。"""
    from app.config import settings

    with _lock:
        if _state.initialized:
            return
        _state.initialized = True
        if not _has_module("agents"):
            _state.status = "unavailable"
            return
        try:
            from agents.tracing import set_trace_provider
            from agents.tracing.provider import DefaultTraceProvider

            # SDK 0.20 lazily creates a cloud exporter inside get_trace_provider.
            # Install an empty provider directly, before any tracing utility can
            # request it. No default HTTP client or cloud processor is created.
            provider = DefaultTraceProvider()
            set_trace_provider(provider)
            _state.sdk_provider = provider
            if not settings.agent_trace_enabled:
                _state.status = "disabled"
                return
            if not settings.agent_trace_api_key:
                _state.status = "unconfigured"
                return
            _initialize_exporter()
        except Exception:
            # 观测边界只记录安全分类；不打印配置、异常或响应正文。
            _state.status = "unavailable"
            _state.boundary_errors += 1
            _release_exporter()
            _clear_sdk_processors()
            logger.warning("Agent tracing unavailable; business execution remains enabled")


def execution_provider_available() -> bool:
    """Confirm SDK execution cannot lazily restore the default cloud exporter."""
    return _state.sdk_provider is not None


def _clear_sdk_processors() -> None:
    """Clear only our prepared provider, never instantiate a default one at exit."""
    if _state.sdk_provider is not None:
        try:
            _state.sdk_provider.set_processors([])
        except Exception:
            _state.boundary_errors += 1


def _initialize_exporter() -> None:
    """安装已锁定的原生 SDK→OpenInference→本地 OTLP 链。"""
    from openinference.instrumentation import TraceConfig
    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, SpanLimits, TracerProvider

    from app.config import settings
    from app.services.agent_telemetry.transport import G0SpanProcessor, LocalExportBuffer

    class BusinessSpanProcessor(G0SpanProcessor):
        """仅允许安全运行标识与模型用量，正文和原始异常不进入队列。"""

        def on_end(self, span: ReadableSpan) -> None:
            try:
                request = encode_spans([span])
                for resource in request.resource_spans:
                    for scope in resource.scope_spans:
                        for item in scope.spans:
                            allowed = []
                            for attribute in item.attributes:
                                key = attribute.key
                                if key in {
                                    "openinference.span.kind", "user.id", "session.id",
                                    "metadata", "llm.model_name", "llm.system", "llm.provider",
                                } or key.startswith("llm.token_count."):
                                    allowed.append(attribute)
                            del item.attributes[:]
                            item.attributes.extend(allowed)
                            item.status.message = ""
                            del item.events[:]
                self.buffer.submit(request)
            except Exception:
                self.buffer.record_boundary_error()

    buffer = LocalExportBuffer(
        settings.agent_trace_endpoint,
        settings.agent_trace_api_key,
        capacity=settings.agent_trace_queue_capacity,
        max_attempts=settings.agent_trace_max_attempts,
        timeout_seconds=settings.agent_trace_timeout_seconds,
    )
    _state.buffer = buffer
    provider = TracerProvider(
        resource=Resource.create({"openinference.project.name": settings.agent_trace_project}),
        span_limits=SpanLimits(max_attributes=128, max_events=16, max_attribute_length=4096),
    )
    _state.provider = provider
    provider.add_span_processor(BusinessSpanProcessor(buffer))
    instrumentor = OpenAIAgentsInstrumentor()
    _state.instrumentor = instrumentor
    instrumentor.instrument(
        tracer_provider=provider,
        exclusive_processor=True,
        config=TraceConfig(
            hide_inputs=True,
            hide_outputs=True,
            hide_llm_invocation_parameters=True,
            hide_llm_tools=True,
        ),
    )
    _state.status = "enabled"


def snapshot() -> dict[str, str | int]:
    """返回安全自监控计数；不将关闭导出解释为业务故障。"""
    result: dict[str, str | int] = {
        "status": _state.status, "initialization_errors": _state.boundary_errors,
    }
    if _state.buffer:
        result.update(_state.buffer.snapshot())
        if result.get("unavailable"):
            result["status"] = "unavailable"
    return result


def flush(timeout_seconds: float = 3) -> bool:
    """仅供停机与验收调用；业务请求不等待 flush。"""
    return _state.buffer.flush(min(max(timeout_seconds, 0), 3)) if _state.buffer else True


def shutdown() -> None:
    """有界关闭，并清空反注册时恢复的默认出口，避免退出时云端导出。"""
    global _state
    with _lock:
        _release_exporter()
        _clear_sdk_processors()
        _state = _TracingState()


def _release_exporter() -> None:
    """释放部分初始化或完整初始化的资源；故障只增加安全计数。"""
    try:
        if _state.instrumentor:
            _state.instrumentor.uninstrument()
    except Exception:
        _state.boundary_errors += 1
    finally:
        _state.instrumentor = None
    try:
        if _state.provider:
            _state.provider.shutdown()
        elif _state.buffer:
            _state.buffer.close(2)
    except Exception:
        _state.boundary_errors += 1
    finally:
        _state.provider = None
        _state.buffer = None


@contextmanager
def run_trace(run: TraceRun) -> Iterator[None]:
    """绑定一个出题根 trace；生命周期异常只影响观测，不吞掉业务异常。"""
    initialize()
    if run.backend != "sdk" or not _has_module("agents"):
        yield
        return
    from agents import trace

    metadata = _metadata(run)
    if _state.status == "enabled":
        from openinference.instrumentation import using_attributes

        token = _span_metadata.set(metadata)
        try:
            with using_attributes(
                user_id=run.owner_user_id,
                session_id=run.session_id or "",
                metadata=metadata,
            ):
                with trace(
                    "generation." + run.entrypoint,
                    trace_id=run.sdk_trace_id,
                    group_id=run.session_id,
                    metadata=metadata,
                ):
                    yield
        finally:
            _span_metadata.reset(token)
    else:
        with trace(
            "generation." + run.entrypoint,
            trace_id=run.sdk_trace_id,
            group_id=run.session_id,
            metadata=metadata,
        ):
            yield


@contextmanager
def stage_span(name: str, metadata: Mapping[str, object] | None = None) -> Iterator[None]:
    """为确定性业务阶段增加 SDK 子 span，数据只允许安全标识和计数。"""
    if not _has_module("agents") or not _state.initialized:
        yield
        return
    from agents.tracing import custom_span, get_current_trace

    if get_current_trace() is None:
        yield
        return
    safe = {
        key: value for key, value in (metadata or {}).items()
        if key in {"stage_id", "question_id", "question_revision_id", "attempt_id", "count"}
        and isinstance(value, (str, int, float, bool, type(None)))
    }
    if _state.status == "enabled":
        from openinference.instrumentation import using_attributes

        # OI 2.7 ignores custom_span.data. Its context metadata is the supported
        # path shared by the stage and every native Agent/LLM child span.
        combined = {**_span_metadata.get(), **safe}
        token = _span_metadata.set(combined)
        try:
            with using_attributes(metadata=combined):
                with custom_span(name):
                    yield
        finally:
            _span_metadata.reset(token)
    else:
        with custom_span(name):
            yield

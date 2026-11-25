"""Optional, metadata-only Phoenix tracing for the existing OpenAI HTTP client.

The provider is private: no global instrumentation, request bodies, exception
messages or user attributes are collected. Export is bounded and best effort.
"""
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from functools import wraps
import logging
from queue import Empty, Full, Queue
import re
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, ParamSpec, TypeVar
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from openai import DefaultHttpxClient

if TYPE_CHECKING:
    from httpx._client import UseClientDefault
    from httpx._types import AuthTypes
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.trace import Span

    from app.config import Settings
    from app.schemas.api import GenerationReviewGroup

logger = logging.getLogger(__name__)
P = ParamSpec("P")
T = TypeVar("T")
_IDENTIFIER = re.compile(r"[a-zA-Z0-9_.:-]{1,100}\Z")


@dataclass(frozen=True)
class _RunContext:
    run_id: str
    entrypoint: str
    span: "Span"


_run: ContextVar[_RunContext | None] = ContextVar("phoenix_run", default=None)


_QUESTION_STAGES = frozenset({
    "planning", "nomination", "generation", "refill", "candidate_review", "independent_solve",
    "solution_completion", "repair", "re_review", "final_acceptance", "corpus_dedup",
    "finished_dedup", "delivery", "summary", "symbolic_solve",
})
_QUESTION_DECISIONS = frozenset({
    "formed", "passed", "rejected", "repaired", "failed", "selected", "skipped", "committed",
})
_REASON_CODES = {
    "题面缺陷": "invalid_stem",
    "题设不足": "insufficient_conditions",
    "命题为假": "false_proposition",
    "条件矛盾": "contradictory_conditions",
    "无法验证": "unverifiable",
    "答案不成立": "invalid_answer",
    "解析不成立": "invalid_explanation",
    "解析方法超出范围": "explanation_out_of_scope",
    "解析补全失败": "solution_completion_failed",
    "补全结论与答案冲突": "answer_conflict",
    "解析为空": "empty_explanation",
    "解析公式格式错误": "explanation_formula",
    "解析含草稿": "explanation_draft",
    "选项不合格": "invalid_options",
    "超出范围": "out_of_scope",
    "难度不符": "difficulty_mismatch",
    "原题选项缺失": "original_options_missing",
    "原题被改动": "original_changed",
    "重复题目": "duplicate",
    "原题选项缺失或无法与材料核对": "original_options_unverified",
    "生成未返回可用候选题": "no_usable_candidates",
    "生成未返回候选题": "refill_underproduced",
    "首轮候选产出不足": "initial_underproduced",
    "可用原题不足": "original_shortage",
}
_SAFE_REASON_CODES = frozenset(_REASON_CODES.values()) | {
    "wrong_type", "quota_filled", "invalid_output", "generation_underproduced",
    "legacy_stem", "exact_duplicate", "semantic_duplicate",
    "embedding_unavailable", "verdict_unavailable", "verdict_uncertain",
}
_QUESTION_FAILURE_PRIORITY = (
    "protected_fields_changed", "independent_options_mismatch", "invalid_distractors",
    "answer_conflict", "explanation_formula", "explanation_draft", "empty_explanation",
    "missing_conclusion", "missing_evidence", "invalid_output",
    "symbolic_unsupported", "symbolic_timeout", "symbolic_error",
    "unverifiable_output", "model_timeout", "model_rate_limit", "model_auth", "model_balance",
    "model_error", "duplicate_check_failed",
)
_QUESTION_FAILURE_CODES = frozenset(_QUESTION_FAILURE_PRIORITY)
_SAFE_REASON_CODES |= _QUESTION_FAILURE_CODES
_REPAIR_MODES = frozenset({"explanation_only", "full"})
_QUESTION_TYPES = frozenset({"single", "multiple", "judge", "blank", "compute", "essay"})
_DIFFICULTIES = frozenset({"低", "中", "高", "地狱"})
_CANDIDATE_ID = re.compile(r"q-[a-f0-9]{10}\Z")
_question_parent: ContextVar["Span | None"] = ContextVar("phoenix_question_parent", default=None)
_refill_round: ContextVar[int] = ContextVar("phoenix_refill_round", default=0)


def _reason_code(reason: str) -> str:
    if reason in _SAFE_REASON_CODES:
        return reason
    if reason in _REASON_CODES:
        return _REASON_CODES[reason]
    from app.services.rag.llm import model_error_trace_code

    return model_error_trace_code(reason)


@dataclass
class QuestionStage:
    """Write a sanitized business decision independently of the span status."""

    span: "Span | None"
    _failures: set[str] = field(default_factory=set)
    _failure_lock: Lock = field(default_factory=Lock)

    def failure(self, code: str) -> None:
        """Collect a safe reason from a retry or one of the phase's parallel peers."""
        if code in _QUESTION_FAILURE_CODES:
            with self._failure_lock:
                self._failures.add(code)

    def failure_reason(self) -> str | None:
        """Select the primary failure deterministically across parallel peers."""
        with self._failure_lock:
            return next((code for code in _QUESTION_FAILURE_PRIORITY if code in self._failures), None)

    def decision(self, outcome: str, reason: str | None = None) -> None:
        """Record a known decision with an optional allowlisted reason."""
        if self.span is None or outcome not in _QUESTION_DECISIONS:
            return
        try:
            self.span.set_attribute("mathcraft.decision", outcome)
            reason_code = _reason_code(reason) if reason is not None else None
            if outcome in {"failed", "rejected"} and reason_code in {
                None, "unverifiable", "solution_completion_failed",
            }:
                reason_code = self.failure_reason() or reason_code
            if reason_code is not None:
                self.span.set_attribute("mathcraft.reason_code", reason_code)
            with self._failure_lock:
                if self._failures:
                    self.span.set_attribute("mathcraft.failure_codes", sorted(self._failures))
        except Exception:
            logger.warning("Phoenix question decision unavailable")

    def generation_counts(self, requested: int, produced: int) -> None:
        """Record candidate counts even when a recoverable model error occurs."""
        if self.span is None:
            return
        try:
            self.span.set_attribute("mathcraft.candidates.requested", requested)
            self.span.set_attribute("mathcraft.candidates.produced", produced)
        except Exception:
            logger.warning("Phoenix generation counts unavailable")

_NOOP_STAGE = QuestionStage(None)
_question_observation: ContextVar[QuestionStage | None] = ContextVar(
    "phoenix_question_observation", default=None,
)


@contextmanager
def question_round(round_number: int) -> Iterator[None]:
    """Bind one delivery round to the current execution and its workers."""
    token = _refill_round.set(round_number)
    try:
        yield
    finally:
        _refill_round.reset(token)


@contextmanager
def question_stage(
    stage: str, *, candidate_id: str | None = None, kind: str | None = None,
    difficulty: str | None = None, revision: int | None = None, repair_mode: str | None = None,
) -> Iterator[QuestionStage]:
    """Parent model calls and record a metadata-only generation or review stage."""
    runtime, context = _runtime, _run.get()
    if runtime is None or context is None or stage not in _QUESTION_STAGES:
        if stage == "solution_completion":
            observation = QuestionStage(None)
            token = _question_observation.set(observation)
            try:
                yield observation
            finally:
                _question_observation.reset(token)
        else:
            yield _NOOP_STAGE
        return
    attributes: dict[str, str | int] = {
        "openinference.span.kind": "CHAIN",
        "mathcraft.run_id": context.run_id,
        "mathcraft.stage": stage,
    }
    if stage != "summary":
        attributes["mathcraft.refill_round"] = _refill_round.get()
    if candidate_id is not None and _CANDIDATE_ID.fullmatch(candidate_id):
        attributes["mathcraft.candidate_id"] = candidate_id
    if kind is not None and kind in _QUESTION_TYPES:
        attributes["mathcraft.question_type"] = kind
    if difficulty is not None and difficulty in _DIFFICULTIES:
        attributes["mathcraft.target_difficulty"] = difficulty
    if revision in (0, 1):
        attributes["mathcraft.revision"] = revision
    if stage == "repair" and repair_mode in _REPAIR_MODES:
        attributes["mathcraft.repair_mode"] = repair_mode
    try:
        from opentelemetry.trace import set_span_in_context

        span = runtime.provider.get_tracer("mathcraft.phoenix").start_span(
            "mathcraft.question." + stage,
            context=set_span_in_context(_question_parent.get() or context.span),
            attributes=attributes,
        )
    except Exception:
        logger.warning("Phoenix question stage unavailable")
        span = None

    token = _question_parent.set(span or _question_parent.get())
    observation = QuestionStage(span)
    observation_token = _question_observation.set(observation)
    error = None
    try:
        yield observation
    except BaseException as exc:
        from app.services.generation_cancellation import GenerationCanceled

        error = "CANCELED" if isinstance(exc, GenerationCanceled) else "EXECUTION_ERROR"
        raise
    finally:
        _question_observation.reset(observation_token)
        _question_parent.reset(token)
        _end(span, error)


def record_question_failure(code: str) -> None:
    """Record an allowlisted failure on the current phase, including failed retries."""
    if observation := _question_observation.get():
        observation.failure(code)


def question_decision(
    stage: str, outcome: str, reason: str | None = None, *,
    candidate_id: str | None = None, kind: str | None = None, difficulty: str | None = None,
    revision: int | None = None,
) -> None:
    """Emit a completed stage for a decision without a model call."""
    with question_stage(
        stage, candidate_id=candidate_id, kind=kind, difficulty=difficulty, revision=revision,
    ) as observation:
        observation.decision(outcome, reason)


def record_question_delivery(groups: "Sequence[GenerationReviewGroup]") -> None:
    """Emit the teacher's group totals after the business result commits."""
    if _runtime is None or _run.get() is None:
        return
    for group in groups:
        with question_stage(
            "summary", kind=group.type.value, difficulty=group.difficulty.value,
        ) as observation:
            span = observation.span
            if span is None:
                continue
            observation.decision("committed")
            try:
                span.set_attribute("mathcraft.requested", group.requested)
                span.set_attribute("mathcraft.delivered", group.delivered)
                span.set_attribute("mathcraft.missing", group.missing)
                for category, counts in (
                    ("rejections", group.rejections), ("generation_events", group.generation_events),
                ):
                    for code, count in _reason_counts(counts).items():
                        span.set_attribute(f"mathcraft.{category}.{code}", count)
            except Exception:
                logger.warning("Phoenix question summary unavailable")


def _reason_counts(counts: dict[str, int]) -> dict[str, int]:
    merged: Counter[str] = Counter()
    for reason, count in counts.items():
        merged[_reason_code(reason)] += count
    return dict(merged)


class _Sender:
    """Own one finite export queue and a daemon that never blocks model calls."""

    def __init__(self, endpoint: str, key: str, capacity: int, timeout: float) -> None:
        self.queue: Queue[Sequence["ReadableSpan"]] = Queue(capacity)
        self.dropped = Event()
        self.endpoint = endpoint
        self.key = key
        self.timeout = timeout
        self.stop = Event()
        self.thread = Thread(target=self._work, name="phoenix-export", daemon=True)
        self.thread.start()

    def submit(self, spans: Sequence["ReadableSpan"]) -> bool:
        """Drop rather than wait when export is unavailable or backlogged."""
        if self.stop.is_set():
            return False
        try:
            self.queue.put_nowait(spans)
            return True
        except Full:
            self.dropped.set()
            return False

    def _work(self) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceResponse,
        )
        from google.protobuf.message import DecodeError
        from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

        headers = {"Content-Type": "application/x-protobuf"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        # Never use deployment proxy variables or follow redirects with the key.
        with httpx.Client(timeout=self.timeout, trust_env=False, follow_redirects=False) as client:
            while not self.stop.is_set():
                if self.dropped.is_set():
                    self.dropped.clear()
                    logger.warning("Phoenix export queue full; metadata dropped")
                try:
                    spans = self.queue.get(timeout=0.1)
                except Empty:
                    continue
                try:
                    try:
                        payload = encode_spans(spans).SerializeToString()
                    except Exception:
                        logger.warning("Phoenix metadata encoding unavailable")
                        continue
                    if len(payload) > 64 * 1024:
                        logger.warning("Phoenix export payload limit exceeded; metadata dropped")
                        continue
                    with client.stream(
                        "POST", self.endpoint, content=payload, headers=headers,
                    ) as res:
                        if not 200 <= res.status_code < 300:
                            raise ValueError("EXPORT_REJECTED")
                        body = bytearray()
                        for chunk in res.iter_bytes():
                            body.extend(chunk)
                            if len(body) > 16384 or self.stop.is_set():
                                raise ValueError("EXPORT_RESPONSE_LIMIT")
                        result = ExportTraceServiceResponse.FromString(bytes(body))
                        if result.partial_success.rejected_spans:
                            raise ValueError("EXPORT_PARTIALLY_REJECTED")
                except (httpx.HTTPError, ValueError, DecodeError):
                    logger.warning("Phoenix export failed; metadata dropped")
                finally:
                    self.queue.task_done()

    def close(self) -> None:
        """Stop within a fixed budget; queued metadata is not a durable log."""
        self.stop.set()
        self.thread.join(timeout=2)


@dataclass
class _Runtime:
    provider: "TracerProvider"
    sender: _Sender


_runtime: _Runtime | None = None


def configure(config: "Settings") -> bool:
    """Enable the private provider, or report unavailable without breaking startup."""
    global _runtime
    shutdown()
    if not config.phoenix_enabled:
        return False
    try:
        endpoint = urlsplit(config.phoenix_endpoint)
        port = endpoint.port
    except ValueError:
        logger.warning("Phoenix unavailable: invalid optional tracing endpoint")
        return False
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or (port is not None and not 1 <= port <= 65535)
            or endpoint.path != "/v1/traces"
            or (endpoint.scheme == "http"
                and endpoint.hostname not in {"localhost", "127.0.0.1", "::1"})
            or not _IDENTIFIER.fullmatch(config.phoenix_project)
            or not 1 <= config.phoenix_queue_size <= 4096
            or not 0 < config.phoenix_timeout_seconds <= 2):
        logger.warning("Phoenix unavailable: invalid optional tracing configuration")
        return False
    sender: _Sender | None = None
    try:
        from opentelemetry.exporter.otlp.proto.common import trace_encoder  # noqa: F401
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            SimpleSpanProcessor, SpanExporter, SpanExportResult,
        )

        sender = _Sender(
            config.phoenix_endpoint, config.phoenix_api_key.get_secret_value(),
            config.phoenix_queue_size, config.phoenix_timeout_seconds,
        )
        export_sender = sender

        class MetadataExporter(SpanExporter):
            def export(self, spans: Sequence["ReadableSpan"]) -> SpanExportResult:
                try:
                    return (SpanExportResult.SUCCESS if export_sender.submit(spans)
                            else SpanExportResult.FAILURE)
                except Exception:
                    # The optional instrumentation boundary must never affect execution.
                    logger.warning("Phoenix export queue unavailable")
                    return SpanExportResult.FAILURE

            def shutdown(self) -> None:
                export_sender.close()

        provider = TracerProvider(
            resource=Resource({
                "service.name": "mathcraft", "openinference.project.name": config.phoenix_project,
            }),
            shutdown_on_exit=False,
        )
        provider.add_span_processor(SimpleSpanProcessor(MetadataExporter()))
        _runtime = _Runtime(provider, sender)
        return True
    except Exception:
        if sender:
            sender.close()
        logger.warning("Phoenix unavailable: optional tracing initialization failed")
        return False


def shutdown() -> None:
    """Release only the provider owned by this extension."""
    global _runtime
    runtime, _runtime = _runtime, None
    if runtime:
        try:
            runtime.provider.shutdown()
        except Exception:
            logger.warning("Phoenix shutdown incomplete")


def current_run_id() -> str | None:
    """Return the active identifier for future ops_runs integration."""
    context = _run.get()
    return context.run_id if context else None


def _end(span: "Span | None", error: str | None = None, *, incomplete: bool = False) -> None:
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        if error:
            span.set_attribute("error.type", error)
        if incomplete:
            span.set_attribute("mathcraft.stream.end", "closed")
        code = StatusCode.ERROR if error else StatusCode.UNSET if incomplete else StatusCode.OK
        span.set_status(Status(code))
        span.end()
    except Exception:
        logger.warning("Phoenix span completion unavailable")


def trace_run(
    entrypoint: str, *, run_id_kwarg: str | None = None, force_new: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Group a current business execution without changing its result or signature."""
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            runtime = _runtime
            if not force_new and (runtime is None or _run.get() is not None):
                return function(*args, **kwargs)
            span = None
            context = None
            if runtime is not None:
                try:
                    supplied = kwargs.get(run_id_kwarg) if run_id_kwarg is not None else None
                    run_id = (supplied if isinstance(supplied, str)
                              and _IDENTIFIER.fullmatch(supplied) else "run_" + uuid4().hex)
                    span = runtime.provider.get_tracer("mathcraft.phoenix").start_span(
                        "mathcraft." + entrypoint,
                        attributes={"openinference.span.kind": "CHAIN", "mathcraft.run_id": run_id,
                                    "mathcraft.entrypoint": entrypoint},
                    )
                    context = _RunContext(run_id, entrypoint, span)
                except Exception:
                    logger.warning("Phoenix run tracing unavailable")
            # A forced business run must not inherit its parent when tracing is unavailable.
            token = _run.set(context)
            parent_token = _question_parent.set(None)
            round_token = _refill_round.set(0)
            error = None
            try:
                return function(*args, **kwargs)
            except BaseException:
                error = "EXECUTION_ERROR"
                raise
            finally:
                _refill_round.reset(round_token)
                _question_parent.reset(parent_token)
                _run.reset(token)
                _end(span, error)
        return wrapped
    return decorate


class TracingThreadPoolExecutor(ThreadPoolExecutor):
    """Carry a separate context snapshot to each generation or review worker."""

    def submit(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        return super().submit(copy_context().run, fn, *args, **kwargs)


def _model_span(model: str) -> "Span | None":
    runtime, context = _runtime, _run.get()
    if runtime is None or context is None:
        return None
    try:
        from opentelemetry.trace import set_span_in_context

        return runtime.provider.get_tracer("mathcraft.phoenix").start_span(
            "openai.chat.completions", context=set_span_in_context(_question_parent.get() or context.span),
            attributes={"openinference.span.kind": "LLM", "mathcraft.run_id": context.run_id,
                        "llm.model_name": model if _IDENTIFIER.fullmatch(model) else "unknown"},
        )
    except Exception:
        logger.warning("Phoenix model tracing unavailable")
        return None


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, inner: httpx.SyncByteStream, span: "Span", status: int) -> None:
        self.inner, self.span, self.status = inner, span, status
        self.finished = False
        self.lock = Lock()

    def _finish(self, error: str | None, *, incomplete: bool = False) -> None:
        with self.lock:
            if not self.finished:
                self.finished = True
                _end(self.span, error, incomplete=incomplete)

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self.inner
        except BaseException:
            self._finish("STREAM_INTERRUPTED")
            raise
        else:
            self._finish("HTTP_ERROR" if self.status >= 400 else None)

    def close(self) -> None:
        try:
            self.inner.close()
        finally:
            # SDKs also close healthy SSE responses at [DONE], before HTTP EOF.
            # A transport-level close alone cannot establish success or cancellation.
            error = "HTTP_ERROR" if self.status >= 400 else None
            self._finish(error, incomplete=error is None)


class MetadataClient(DefaultHttpxClient):
    """Observe requests while preserving SDK proxy, redirect and connection defaults."""

    def __init__(self, model: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self.model = model
        super().__init__(transport=transport)

    def send(
        self,
        request: httpx.Request,
        *,
        stream: bool = False,
        auth: "AuthTypes | UseClientDefault | None" = httpx.USE_CLIENT_DEFAULT,
        follow_redirects: "bool | UseClientDefault" = httpx.USE_CLIENT_DEFAULT,
    ) -> httpx.Response:
        """Keep streaming responses open until consumed or explicitly closed."""
        span = (_model_span(self.model) if request.method == "POST"
                and request.url.path.endswith("/chat/completions") else None)
        try:
            response = super().send(
                request, stream=stream, auth=auth, follow_redirects=follow_redirects,
            )
        except BaseException as exc:
            _end(span, "TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "REQUEST_ERROR")
            raise
        if span:
            try:
                span.set_attribute("http.response.status_code", response.status_code)
                if response.is_stream_consumed:
                    _end(span, "HTTP_ERROR" if response.status_code >= 400 else None)
                else:
                    assert isinstance(response.stream, httpx.SyncByteStream)
                    response.stream = _ResponseStream(response.stream, span, response.status_code)
            except Exception:
                _end(span, "TRACING_ERROR")
        return response

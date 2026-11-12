"""Request-local generation facts, without content, persistence or model calls.

Only an injected sink retains events. A run owns its backend and revision state for
its complete lifetime, including both conversation commits. Instrumentation errors
are isolated from business errors; SDK availability is an execution prerequisite.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from threading import RLock
from typing import Literal, ParamSpec, TypeVar, cast
from uuid import uuid4

from app.config import settings
from app.schemas.question import Question

Backend = Literal["sdk", "legacy"]
Entrypoint = Literal["parameterized", "conversation"]
Outcome = Literal["completed", "failed", "cancelled", "needs_confirmation"]
Fact = str | int | bool | None
P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")
logger = logging.getLogger("app.generation.observation")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_MAX_TRACKED_QUESTIONS = 4096
_EVENT_TYPES = {
    "accepted": "run.accepted",
    "started": "run.started",
    "ended": "run.ended",
    "revision": "question.revised",
    "review": "review.recorded",
    "regen.started": "regeneration.started",
    "regen.ended": "regeneration.finished",
    "regen.result": "regeneration.result",
    "degradation": "degradation.selected",
    "conversation.dependency": "dependency.observed",
}
_FACT_KEYS = frozenset({
    "stage", "stage_id", "parent_stage_id", "status", "reason", "dependency",
    "question_id", "question_revision_id", "previous_question_revision_id", "version", "scope",
    "stem_changed", "options_changed", "answer_changed", "analysis_changed",
    "attempt_id", "question_type", "requested_count", "question_count", "round",
    "kind", "available", "reviewed", "review_count", "unknown", "passed",
    "judges", "arbitrated", "duplicate_count", "review_kind",
})


@dataclass(frozen=True)
class GenerationEvent:
    """Safe identifiers and counters at an observed execution boundary."""

    event_schema_version: int
    event_id: str
    occurred_at: str
    event_type: str
    run_id: str
    owner_user_id: str
    entrypoint: Entrypoint
    backend: Backend
    session_id: str | None
    task_id: str | None
    batch_id: str | None
    sdk_trace_id: str | None
    sequence: int
    metadata: Mapping[str, Fact]

    @property
    def name(self) -> str:
        """Compatibility spelling for the canonical event_type."""
        return self.event_type


EventSink = Callable[[GenerationEvent], None]


@dataclass
class _Revision:
    revision_id: str
    version: int
    fingerprints: tuple[str, ...]
    reviewed: bool = False


@dataclass
class GenerationRun:
    """Minimal in-memory identity and facts for one actual generation execution."""

    owner_user_id: str
    entrypoint: Entrypoint
    backend: Backend
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex}")
    session_id: str | None = None
    task_id: str | None = None
    batch_id: str | None = None
    sdk_trace_id: str = field(default_factory=lambda: f"trace_{uuid4().hex}")
    accepted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    outcome: Outcome = "completed"
    _accepted: bool = field(default=False, repr=False)
    _sequence: int = field(default=0, repr=False)
    _revisions: dict[str, _Revision] = field(default_factory=dict, repr=False)
    _revision_limit_reached: bool = field(default=False, repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False)


_run: ContextVar[GenerationRun | None] = ContextVar("generation_run", default=None)
_sink: ContextVar[EventSink | None] = ContextVar("generation_event_sink", default=None)
_stage: ContextVar[str | None] = ContextVar("generation_stage", default=None)
_conversation_start: ContextVar[Callable[[], GenerationRun] | None] = ContextVar(
    "generation_conversation_start", default=None,
)


def current_run() -> GenerationRun | None:
    """Return the actual generation run, or None for ordinary requests."""
    return _run.get()


def _identifier(value: str | None) -> str | None:
    return value if value is not None and _IDENTIFIER.fullmatch(value) else None


def _safe_metadata(metadata: Mapping[str, Fact]) -> dict[str, Fact]:
    return {
        key: value for key, value in metadata.items()
        if key in _FACT_KEYS and (
            value is None or isinstance(value, (bool, int))
            or (isinstance(value, str) and _identifier(value) is not None)
        )
    }


def emit(name: str, **metadata: Fact) -> None:
    """Send allowlisted facts; never forward text, exceptions or sink failures."""
    run, sink = current_run(), _sink.get()
    if run is None or sink is None:
        return
    with run._lock:
        run._sequence += 1
        event_type = _EVENT_TYPES.get(name, _identifier(name) or "observation")
        event = GenerationEvent(
            event_schema_version=1, event_id=f"event_{uuid4().hex}",
            occurred_at=(run.accepted_at if event_type == "run.accepted" else
                         datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
            event_type=event_type,
            run_id=run.run_id,
            owner_user_id=_identifier(run.owner_user_id) or "redacted",
            entrypoint=run.entrypoint, backend=run.backend,
            session_id=_identifier(run.session_id), task_id=_identifier(run.task_id),
            batch_id=_identifier(run.batch_id), sdk_trace_id=_identifier(run.sdk_trace_id),
            sequence=run._sequence, metadata=_safe_metadata(metadata),
        )
        try:
            sink(event)
        except Exception:
            logger.warning("Generation event sink failed; business execution continues")


@contextmanager
def event_sink(sink: EventSink) -> Iterator[None]:
    """Inject a request-local collector, also inherited by copied thread contexts."""
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def _trace_context(
    name: str | None = None, metadata: Mapping[str, Fact] | None = None,
) -> Iterator[None]:
    """Keep tracing setup/teardown failures from changing business outcomes."""
    run = current_run()
    if run is None:
        yield
        return
    stack = ExitStack()
    try:
        from app.services import agent_tracing

        context = (
            # TraceRun only reads these fields; Literal string attributes satisfy
            # that boundary although its mutable protocol fields are invariant.
            agent_tracing.run_trace(cast(agent_tracing.TraceRun, run)) if name is None
            else agent_tracing.stage_span(name, metadata=dict(metadata or {}))
        )
        stack.enter_context(context)
    except Exception:
        logger.warning("Generation tracing unavailable; business execution continues")
    try:
        yield
    finally:
        error = sys.exc_info()
        try:
            stack.__exit__(*error)
        except Exception:
            logger.warning("Generation tracing close failed; business execution continues")


@contextmanager
def generation_scope(
    owner_user_id: str,
    entrypoint: Entrypoint,
    *,
    session_id: str | None = None,
    task_id: str | None = None,
    run: GenerationRun | None = None,
) -> Iterator[GenerationRun]:
    """Open the sole run/root trace after SDK availability has been checked."""
    if run is None:
        backend = ensure_backend_available()
        run = GenerationRun(
            owner_user_id, entrypoint, backend, session_id=session_id, task_id=task_id,
        )
    else:
        if (run.owner_user_id, run.entrypoint, run.session_id, run.task_id) != (
            owner_user_id, entrypoint, session_id, task_id,
        ):
            raise ValueError("Generation run identity does not match execution")
        ensure_backend_available(run.backend)
    token = _run.set(run)
    stage_token = _stage.set(None)
    try:
        with _trace_context():
            if not run._accepted:
                _record_accepted(run)
            emit("started")
            try:
                yield run
            except asyncio.CancelledError:
                run.outcome = "cancelled"
                raise
            except BaseException:
                run.outcome = "failed"
                raise
            finally:
                emit("ended", status=run.outcome)
    finally:
        run._revisions.clear()
        _stage.reset(stage_token)
        _run.reset(token)


def ensure_backend_available(backend: Backend | None = None) -> Backend:
    """Check SDK dependencies before admission; legacy requires no SDK imports."""
    backend = backend if backend is not None else settings.generation_llm_backend
    if backend == "sdk":
        from app.services import agent_sdk

        agent_sdk.ensure_available()
    return backend


def _record_accepted(run: GenerationRun) -> None:
    run._accepted = True
    emit("accepted")


def accept_generation(
    owner_user_id: str,
    entrypoint: Entrypoint,
    *,
    backend: Backend,
    task_id: str | None = None,
    session_id: str | None = None,
) -> GenerationRun:
    """Record successful admission after prerequisites, without opening a trace.

    The caller has checked backend availability and acquired its admission lock.
    Pass this identity to generation_scope when the execution body really starts.
    """
    run = GenerationRun(
        owner_user_id, entrypoint, backend, session_id=session_id, task_id=task_id,
    )
    token = _run.set(run)
    try:
        _record_accepted(run)
    finally:
        _run.reset(token)
    return run


def mark_outcome(outcome: Outcome) -> None:
    """Record a caught business outcome; only scope exit emits authoritative ended."""
    run = current_run()
    if run is not None:
        run.outcome = outcome


@contextmanager
def conversation_scope(owner_user_id: str, session_id: str) -> Iterator[None]:
    """Defer starting until chat_flow resolves slots; retain context through commits."""
    with ExitStack() as stack:
        chosen: GenerationRun | None = None

        def start() -> GenerationRun:
            nonlocal chosen
            if chosen is None:
                chosen = stack.enter_context(generation_scope(
                    owner_user_id, "conversation", session_id=session_id,
                ))
                emit("conversation.context_bound")
                emit("conversation.dependency", dependency="slots", status="resolved")
            return chosen

        token = _conversation_start.set(start)
        try:
            yield
        finally:
            _conversation_start.reset(token)


def start_conversation_run(*, hyde_available: bool = False) -> None:
    """Called only after complete slots have selected an actual generation flow."""
    start = _conversation_start.get()
    if start is not None and current_run() is None:
        start()
        emit(
            "conversation.dependency", dependency="hyde", available=hyde_available, scope="pre_run",
        )


@contextmanager
def stage(name: str, **metadata: Fact) -> Iterator[None]:
    """Observe a fixed business stage with thread-local parent linkage."""
    if current_run() is None:
        yield
        return
    stage_id, parent_id = uuid4().hex, _stage.get()
    facts = _safe_metadata(metadata)
    emit("stage.started", stage=name, stage_id=stage_id, parent_stage_id=parent_id, **facts)
    token = _stage.set(stage_id)
    status = "completed"
    try:
        with _trace_context(name, {**facts, "stage_id": stage_id}):
            yield
    except BaseException:
        status = "failed"
        raise
    finally:
        emit("stage.ended", stage=name, stage_id=stage_id, status=status)
        _stage.reset(token)


def observed_stage(name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate synchronous fixed stages without changing signatures or retries."""
    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with stage(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def degradation(reason: str) -> None:
    """Record a fixed fallback code, never an exception or its message."""
    emit("degradation", reason=reason)


def observe_question(question: Question, reason: str) -> str | None:
    """Create a new content revision whenever stem/options/answer/analysis change."""
    run = current_run()
    if run is None:
        return None
    values = (
        question.stem, [(o.label, o.text) for o in question.options],
        question.answer, question.analysis,
    )
    fingerprints = tuple(
        hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()
        for value in values
    )
    with run._lock:
        previous = run._revisions.get(question.id)
        if previous is None and len(run._revisions) >= _MAX_TRACKED_QUESTIONS:
            if not run._revision_limit_reached:
                run._revision_limit_reached = True
                degradation("revision_capacity_reached")
            return None
        if previous is not None and previous.fingerprints == fingerprints:
            return previous.revision_id
        revision = _Revision(uuid4().hex, previous.version + 1 if previous else 1, fingerprints)
        run._revisions[question.id] = revision
        changes = {
            f"{name}_changed": (
                previous is None or previous.fingerprints[index] != fingerprints[index]
            )
            for index, name in enumerate(("stem", "options", "answer", "analysis"))
        }
        emit(
            "revision", question_id=question.id, question_revision_id=revision.revision_id,
            previous_question_revision_id=previous.revision_id if previous else None,
            version=revision.version, reason=reason, **changes,
        )
        return revision.revision_id


def record_review(question: Question, *, passed: bool, unknown: bool) -> None:
    """Bind existing blind-review evidence to the exact version and stem-only scope."""
    run = current_run()
    if run is None:
        return
    with run._lock:
        revision_id = observe_question(question, "review")
        if revision_id is None:
            return
        run._revisions[question.id].reviewed = not unknown
        emit(
            "review", question_id=question.id, question_revision_id=revision_id,
            scope="stem", review_kind="difficulty", passed=passed and not unknown, unknown=unknown,
        )


@contextmanager
def regeneration_attempt(reason: str, **metadata: Fact) -> Iterator[str]:
    """Pair real regeneration starts/ends; counts never derive from legacy stats."""
    attempt_id = uuid4().hex
    emit("regen.started", attempt_id=attempt_id, reason=reason, **metadata)
    status = "completed"
    try:
        with _trace_context("regeneration.attempt", {"attempt_id": attempt_id}):
            yield attempt_id
    except BaseException:
        status = "failed"
        raise
    finally:
        emit("regen.ended", attempt_id=attempt_id, reason=reason, status=status)


@contextmanager
def delivery(kind: str, *, batch_id: str | None = None, question_count: int = 0) -> Iterator[None]:
    """Emit committed only after this individual SQL commit actually returns."""
    emit("delivery.started", kind=kind, question_count=question_count)
    try:
        yield
    except BaseException:
        emit("delivery.failed", kind=kind)
        raise
    else:
        run = current_run()
        if run is not None and batch_id is not None:
            run.batch_id = batch_id
        emit("delivery.committed", kind=kind, question_count=question_count)


def record_delivered_question(question: Question) -> None:
    """Report exact delivered revision and whether this version has review evidence."""
    run = current_run()
    if run is None:
        return
    with run._lock:
        revision_id = observe_question(question, "delivery")
        revision = run._revisions.get(question.id)
        emit(
            "delivery.question", question_id=question.id, question_revision_id=revision_id,
            reviewed=revision.reviewed if revision is not None else False,
            scope="stem", review_kind="difficulty",
        )


def map_in_context(
    pool: ThreadPoolExecutor, function: Callable[[T], R], values: Iterable[T],
) -> Iterator[R]:
    """Submit every item with a fresh Context, preserving map's result ordering."""
    futures = [pool.submit(copy_context().run, function, value) for value in values]
    return (future.result() for future in futures)

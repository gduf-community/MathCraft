"""Run the bounded question verifier in a disposable Python process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from threading import BoundedSemaphore
from time import monotonic
from typing import Literal

SymbolicStatus = Literal["solved", "unsupported", "timeout", "error"]
CancellationCheck = Callable[[], bool | None]

_TIMEOUT_SECONDS = 8.0
_POLL_SECONDS = 0.05
_MAX_TEXT = 1024
_MAX_OPTIONS = 12
_MAX_RESPONSE = 8192
_WORKERS = BoundedSemaphore(2)
_WORKER_PATH = Path(__file__).with_name("_question_symbolic_worker.py")


@dataclass(frozen=True, slots=True)
class SymbolicResult:
    """Exact answer and optional comparisons against the supplied answer and options."""

    status: SymbolicStatus
    answer: str = ""
    answer_matches: bool | None = None
    true_option_indices: tuple[int, ...] | None = None
    _problem: tuple[str, str] | None = field(default=None, repr=False, compare=False)


def solve_symbolic(
    stem: str, kind: str, cancel_check: CancellationCheck | None = None,
) -> SymbolicResult:
    """Solve a supported complete stem using exact arithmetic in an isolated worker."""
    if cancel_check is not None and cancel_check():
        return SymbolicResult("timeout")
    if kind not in {"single", "multiple", "blank", "compute"} or not _bounded(stem):
        return SymbolicResult("unsupported")
    return _run((stem, kind), None, (), cancel_check)


def verify_symbolic(
    result: SymbolicResult,
    answer_text: str,
    options: tuple[str, ...],
    cancel_check: CancellationCheck | None = None,
) -> SymbolicResult:
    """Compare answer text and each ordered option with the independently derived solution.

    For explicit root-selection stems, compare each option as a single root and
    compare the submitted set against the correct values present in the choices.
    Otherwise, compare each option and answer against the full solution.
    Option indices are zero-based. A None comparison indicates insufficient coverage.
    """
    if cancel_check is not None and cancel_check():
        return SymbolicResult("timeout")
    if result.status != "solved":
        return result
    if (
        result._problem is None
        or not _bounded(answer_text)
        or len(options) > _MAX_OPTIONS
        or not all(_bounded(option) for option in options)
    ):
        return SymbolicResult("unsupported", result.answer)
    return _run(result._problem, answer_text, options, cancel_check)


def _bounded(text: str) -> bool:
    return 0 < len(text) <= _MAX_TEXT and bool(text.strip())


def _run(
    problem: tuple[str, str],
    answer_text: str | None,
    options: tuple[str, ...],
    cancel_check: CancellationCheck | None,
) -> SymbolicResult:
    deadline = monotonic() + _TIMEOUT_SECONDS
    while True:
        if cancel_check is not None and cancel_check():
            return SymbolicResult("timeout")
        remaining = deadline - monotonic()
        if remaining <= 0:
            return SymbolicResult("timeout")
        if _WORKERS.acquire(timeout=min(remaining, _POLL_SECONDS)):
            break

    try:
        with ExitStack() as stack:
            try:
                request = stack.enter_context(tempfile.TemporaryFile())
                response = stack.enter_context(tempfile.TemporaryFile())
                request.write(json.dumps((problem[0], answer_text, options)).encode("ascii"))
                request.seek(0)
                env = {
                    name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "TMP", "TEMP")
                    if name in os.environ
                }
                if monotonic() >= deadline:
                    return SymbolicResult("timeout")
                worker = stack.enter_context(subprocess.Popen(
                    [sys.executable, "-I", str(_WORKER_PATH)],
                    stdin=request, stdout=response, stderr=subprocess.DEVNULL, env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                ))
            except OSError:
                return SymbolicResult("error")
            try:
                while True:
                    if cancel_check is not None and cancel_check():
                        return SymbolicResult("timeout")
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        return SymbolicResult("timeout")
                    try:
                        exit_code = worker.wait(timeout=min(remaining, _POLL_SECONDS))
                    except subprocess.TimeoutExpired:
                        continue
                    break
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait()
            if cancel_check is not None and cancel_check():
                return SymbolicResult("timeout")
            if exit_code != 0:
                return SymbolicResult("error")
            response.seek(0)
            return _read_result(response.read(_MAX_RESPONSE + 1), problem, len(options))
    finally:
        _WORKERS.release()


def _read_result(
    raw: bytes, problem: tuple[str, str], option_count: int,
) -> SymbolicResult:
    if len(raw) > _MAX_RESPONSE:
        return SymbolicResult("error")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return SymbolicResult("error")
        status = data.get("status")
        answer = data.get("answer", "")
        matches = data.get("answer_matches")
        indices = data.get("true_option_indices")
        if (
            not isinstance(answer, str)
            or (matches is not None and type(matches) is not bool)
            or (indices is not None and (
                not isinstance(indices, list)
                or any(type(index) is not int or not 0 <= index < option_count for index in indices)
            ))
        ):
            return SymbolicResult("error")
    except (ValueError, UnicodeError):
        return SymbolicResult("error")
    if status == "solved" and answer:
        return SymbolicResult("solved", answer, matches, _indices(indices), problem)
    if status == "unsupported":
        return SymbolicResult("unsupported", answer, matches, _indices(indices))
    return SymbolicResult("error")


def _indices(indices: list[int] | None) -> tuple[int, ...] | None:
    return None if indices is None else tuple(indices)

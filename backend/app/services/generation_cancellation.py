"""Explicit cooperative cancellation for generation and review workers."""

from collections.abc import Callable
from typing import ParamSpec, TypedDict, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")


class GenerationCanceled(Exception):
    """The caller canceled this generation; let active workers finish before propagating."""


class CancellationKwargs(TypedDict, total=False):
    """Optional callback keyword, omitted for existing callers without cancellation."""

    cancel_check: Callable[[], None]


def cancellation_kwargs(cancel_check: Callable[[], None] | None) -> CancellationKwargs:
    """Preserve the calling convention of functions used without cancellation."""
    return {"cancel_check": cancel_check} if cancel_check is not None else {}


def check_cancellation(cancel_check: Callable[[], None] | None) -> None:
    """Check only the operation explicitly bound by the caller."""
    if cancel_check is not None:
        cancel_check()


def run_checked(
    check: Callable[[], None] | None,
    function: Callable[_P, _T],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _T:
    """Check before work starts and after it returns or fails, without interrupting it."""
    check_cancellation(check)
    try:
        return function(*args, **kwargs)
    finally:
        check_cancellation(check)

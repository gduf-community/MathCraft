"""Fixed subprocess entry point for the private isolated-worker protocol.

Only the parent runtime writes these pickle files. Callable paths are internal
code constants, never values accepted from an HTTP request.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import pickle
import sys
import traceback
from typing import Any


def _error_envelope(exc: Exception) -> dict[str, Any]:
    attrs = dict(vars(exc))
    # OSError exposes filename as a descriptor rather than in __dict__.
    if hasattr(exc, "filename"):
        attrs["filename"] = exc.filename
    serializable_attrs: dict[str, Any] = {}
    for name, value in attrs.items():
        try:
            pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            # Diagnostic attributes must not prevent the error itself returning.
            continue
        serializable_attrs[name] = value
    return {
        "ok": False,
        "message": str(exc),
        "module": type(exc).__module__,
        "type": type(exc).__name__,
        "traceback": traceback.format_exc(),
        "attrs": serializable_attrs,
    }


def main(argv: list[str] | None = None) -> int:
    """Execute one request and write the envelope expected by isolated_worker."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m MathCraft.runtime.worker_process REQUEST RESULT", file=sys.stderr)
        return 2
    request_path, result_path = map(Path, args)
    try:
        request = pickle.loads(request_path.read_bytes())  # noqa: S301 - private parent file
        module_name, callable_name = request["callable_path"].split(":", 1)
        target = importlib.import_module(module_name)
        for name in callable_name.split("."):
            target = getattr(target, name)
        result = target(*request["args"], **request["kwargs"])
        payload = pickle.dumps({"ok": True, "result": result}, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        payload = pickle.dumps(_error_envelope(exc), protocol=pickle.HIGHEST_PROTOCOL)
    result_path.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

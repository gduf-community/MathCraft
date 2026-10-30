"""Runtime home resolution for installed and source MathCraft runs."""

from __future__ import annotations

import os
from pathlib import Path

MATHCRAFT_HOME_ENV = "MATHCRAFT_HOME"
# Source checkout: <repo>/backend/MathCraft/runtime/home.py, so the package's
# parent is ``backend`` and the repository root is one level above it. Installed
# wheels keep the package's parent (site-packages) as the reference root.
_PACKAGE_DIR = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _PACKAGE_DIR.parent
PACKAGE_ROOT = _SOURCE_ROOT.parent if _SOURCE_ROOT.name == "backend" else _SOURCE_ROOT


def validate_runtime_home(home: str | Path) -> None:
    """Reject runtime homes that point inside this checkout's data tree."""

    resolved = Path(home).expanduser().resolve()
    invalid_homes = {
        PACKAGE_ROOT / "data",
        PACKAGE_ROOT / "data" / "user",
    }
    if resolved in invalid_homes:
        raise ValueError(
            f"Invalid MathCraft runtime home: {resolved}. Runtime data must live under "
            f"{PACKAGE_ROOT / 'data'} without nesting. Start MathCraft with "
            f"MATHCRAFT_HOME={PACKAGE_ROOT} from {PACKAGE_ROOT}."
        )


def get_runtime_home(home: str | Path | None = None) -> Path:
    """Return the directory that owns runtime data for this process.

    Priority:
    1. Explicit *home* argument.
    2. ``MATHCRAFT_HOME`` environment variable.
    3. Current working directory.

    The returned path is the workspace root; runtime data lives below
    ``<home>/data``.
    """

    raw = home if home is not None else os.getenv(MATHCRAFT_HOME_ENV)
    if raw is None or str(raw).strip() == "":
        return Path.cwd().resolve()
    return Path(raw).expanduser().resolve()


def get_runtime_data_root(home: str | Path | None = None) -> Path:
    """Return ``<runtime-home>/data``."""

    return get_runtime_home(home) / "data"


__all__ = [
    "MATHCRAFT_HOME_ENV",
    "PACKAGE_ROOT",
    "get_runtime_home",
    "get_runtime_data_root",
    "validate_runtime_home",
]

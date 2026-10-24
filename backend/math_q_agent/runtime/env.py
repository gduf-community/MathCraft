"""Load the repository-level environment file for local separated startup."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_project_env() -> Path:
    """Load ``.env`` without overriding variables supplied by the shell."""

    env_file = PROJECT_ROOT / ".env"
    load_dotenv(env_file, override=False)
    return env_file


__all__ = ["PROJECT_ROOT", "load_project_env"]

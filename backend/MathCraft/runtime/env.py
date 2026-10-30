"""Load the repository-level environment file for local separated startup."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173


def load_project_env() -> Path:
    """Load ``.env`` without overriding variables supplied by the shell."""

    env_file = PROJECT_ROOT / ".env"
    load_dotenv(env_file, override=False)
    return env_file


__all__ = [
    "PROJECT_ROOT",
    "DEFAULT_BACKEND_HOST",
    "DEFAULT_BACKEND_PORT",
    "DEFAULT_FRONTEND_PORT",
    "load_project_env",
]

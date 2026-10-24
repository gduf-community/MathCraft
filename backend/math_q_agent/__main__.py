"""Run the backend with ``python -m math_q_agent``.

Defaults match a local single-tenant deployment: loopback only, port 8001.
"""

from __future__ import annotations

import argparse
import os

from math_q_agent.runtime.env import load_project_env


def main() -> None:
    load_project_env()
    parser = argparse.ArgumentParser(
        prog="math_q_agent",
        description="Knowledge-base and model-configuration backend.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("BACKEND_HOST", "127.0.0.1"),
        help="bind address (default: BACKEND_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("BACKEND_PORT", "8001")),
        help="bind port (default: BACKEND_PORT or 8001)",
    )
    parser.add_argument("--reload", action="store_true", help="reload on source changes")
    parser.add_argument("--log-level", default="info", help="uvicorn log level (default: info)")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "math_q_agent.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    os.environ.setdefault("MATH_Q_MODE", "server")
    main()

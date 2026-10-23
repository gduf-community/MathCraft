"""Run the backend with ``python -m math_q_agent``.

Defaults match a local single-tenant deployment: loopback only, port 8001.
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="math_q_agent",
        description="Knowledge-base and model-configuration backend.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8001, help="bind port (default: 8001)")
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

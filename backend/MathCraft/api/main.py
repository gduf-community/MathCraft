"""Expose the MathCraft FastAPI application under the public package name."""

from math_q_agent.api.main import app

__all__ = ["app"]

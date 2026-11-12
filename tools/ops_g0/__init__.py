"""Isolated A0/G0 preparation tools; never imported by the MathCraft application."""

from pathlib import Path
import sys

# Shared pure telemetry modules live in backend/app and do not load app settings.
_backend = str(Path(__file__).resolve().parents[2] / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

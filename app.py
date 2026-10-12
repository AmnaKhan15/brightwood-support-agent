"""Entry point for Vercel: it serves the ASGI `app` below as a Vercel Function.

Locally, run the API with `python -m brightwood_support.server` (or the "api" launch config) instead.
On Vercel, configure everything with environment variables (see .env.example); there is no .env file.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from brightwood_support.server import create_app  # noqa: E402
from brightwood_support.telemetry import setup_logging  # noqa: E402

setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
app = create_app()  # the service starts on the first request, so a cold start stays light

"""A standalone job worker, for when the web service and the worker run as separate processes.

    python -m brightwood_support.worker

It needs REDIS_URL (the queue) and DATABASE_URL (the sandboxes it acts on). On Render's free tier
the web process runs an embedded worker instead (EMBEDDED_WORKER=true), so this is optional.
"""
from __future__ import annotations

import os
import signal
import threading

from . import jobs
from .service import Service
from .telemetry import setup_logging


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    if not (os.environ.get("REDIS_URL") and os.environ.get("DATABASE_URL")):
        raise SystemExit("the standalone worker needs REDIS_URL and DATABASE_URL")
    Service()  # configures the jobs with this service and the Redis broker
    worker = jobs.start_embedded_worker(threads=int(os.environ.get("WORKER_THREADS", "4")))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    worker.stop()


if __name__ == "__main__":
    main()

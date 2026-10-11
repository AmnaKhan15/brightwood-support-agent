"""A standalone job worker, for when the web service and the worker run as separate processes.

    python -m brightwood_support.worker

It needs REDIS_URL (the queue) and DATABASE_URL (the sandboxes it acts on). On Render's free tier
the web process runs an embedded worker instead (EMBEDDED_WORKER=true), so this is optional.
"""
from __future__ import annotations

import os
import signal
import threading

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

from . import jobs  # noqa: E402
from .service import Service  # noqa: E402
from .telemetry import setup_logging  # noqa: E402


def main() -> None:
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    if jobs.INLINE or not os.environ.get("DATABASE_URL"):
        raise SystemExit("the standalone worker needs REDIS_URL and DATABASE_URL")
    Service()  # binds itself to the jobs
    worker = jobs.start_embedded_worker(threads=int(os.environ.get("WORKER_THREADS", "4")))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    worker.stop()


if __name__ == "__main__":
    main()

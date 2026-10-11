"""Background jobs: Dramatiq on Redis.

Two kinds of work leave the request path:
  - decide_approval      a manager's decision: resume the approval workflow, which calls the payment
                         provider. Stripe can be slow or fail, so this retries with backoff; the
                         idempotency key on every refund makes a retry safe.
  - apply_refund_event   a verified Stripe webhook: update the refund's status.

`configure(env)` (called by the Service) picks the broker: with REDIS_URL, jobs go to Redis and a
worker runs them (embedded in the web process on the free tier, or `python -m brightwood_support.worker`
as its own process). Without Redis, jobs run immediately in the caller's thread, which keeps tests and
local runs simple and deterministic.
"""
from __future__ import annotations

import logging

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker

log = logging.getLogger(__name__)

broker: dramatiq.Broker = StubBroker()
dramatiq.set_broker(broker)
_inline = True
_service = None


def inline() -> bool:
    """True when jobs run at once in the caller's thread (no Redis configured)."""
    return _inline


def _svc():
    if _service is None:
        raise RuntimeError("jobs.configure(...) was not called")
    return _service


@dramatiq.actor(queue_name="approvals", max_retries=3, min_backoff=2_000, max_backoff=30_000)
def decide_approval(sid: str, approval_id: int, approve: bool, who: str, role: str) -> str:
    return _svc().finish_decision(sid, approval_id, approve, who, role)


@dramatiq.actor(queue_name="webhooks", max_retries=5, min_backoff=1_000, max_backoff=60_000)
def apply_refund_event(provider_refund_id: str, status: str) -> int:
    return _svc().apply_refund_status(provider_refund_id, status)


ACTORS = (decide_approval, apply_refund_event)


def configure(service, redis_url: str = "") -> None:
    """Bind the jobs to `service` and choose the broker: Redis when a URL is given, inline otherwise."""
    global broker, _inline, _service
    _service = service
    _inline = not redis_url
    if _inline or isinstance(broker, RedisBroker):
        return
    broker = RedisBroker(url=redis_url)
    dramatiq.set_broker(broker)
    for actor in ACTORS:
        actor.broker = broker
        broker.declare_actor(actor)


def enqueue(actor, *args):
    """Run now (no Redis) and return the result, or queue it and return None."""
    if _inline:
        return actor.fn(*args)
    actor.send(*args)
    return None


def start_embedded_worker(threads: int = 2):
    """Run a worker inside this process. Render's free tier has no separate worker service."""
    if _inline:
        return None
    worker = dramatiq.Worker(broker, worker_threads=threads)
    worker.start()
    log.info("embedded job worker started", extra={"ctx": {"threads": threads}})
    return worker

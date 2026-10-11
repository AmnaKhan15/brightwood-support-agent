"""LLM gateway: one front door for several model providers.

The agent talks to the gateway as if it were a single model. The gateway:
  1. ROUTES each call to a tier: a cheap, fast model for reading and gathering
     facts, a stronger model once the agent has to decide.
  2. CACHES identical requests, so a repeat costs no model call.
  3. FALLS BACK down an ordered list of providers when one errors or times out.
  4. Uses a CIRCUIT BREAKER, so a provider that keeps failing is skipped at once
     instead of making every request wait for its timeout.
  5. DEGRADES to the fast tier if every strong provider is down, and says so.
  6. Records per-provider calls, failures, latency, fallbacks and cache hits.

Everything here is tested with fake providers. No real provider has been
connected, so the latency and cost numbers a real deployment would show are not
measured yet. The routing rule is a heuristic that a real-model eval must check.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .agent import Model, Reply
from .reliability import CallTimeout, call_with_timeout


class AllProvidersFailed(Exception):
    """No provider could answer. `errors` lists (provider, error) in order."""

    def __init__(self, errors: list[tuple[str, BaseException]]) -> None:
        super().__init__("; ".join(f"{name}: {err!r}" for name, err in errors) or "no provider available")
        self.errors = errors


class CircuitBreaker:
    """Stop calling a provider that keeps failing, then probe it again later.

    closed    -> calls allowed. `failure_threshold` failures in a row open it.
    open      -> calls skipped until `cooldown` seconds pass.
    half-open -> one trial call is allowed. Success closes it; failure re-opens it.
    """

    def __init__(self, failure_threshold: int = 3, cooldown: float = 30.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half-open" if self._clock() - self._opened_at >= self.cooldown else "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold or self._opened_at is not None:
            self._opened_at = self._clock()  # (re)open and restart the cooldown


@dataclass
class Provider:
    name: str
    model: Model
    timeout: float = 20.0
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)


@dataclass
class ProviderStats:
    calls: int = 0
    failures: int = 0
    skipped_open: int = 0
    total_seconds: float = 0.0

    @property
    def avg_seconds(self) -> float:
        done = self.calls - self.failures
        return self.total_seconds / done if done else 0.0


def default_router(messages: list[dict]) -> str:
    """Choose a tier from the conversation so far.

    Heuristic: while the agent is still gathering facts (fewer than 3 tool results),
    use the fast tier. Once it has read the incident and logs it has to decide what
    to do, so use the strong tier. A real-model eval must confirm this is good enough.
    """
    tool_results = sum(1 for m in messages if m.get("role") == "tool")
    return "fast" if tool_results < 3 else "strong"


class Gateway:
    def __init__(
        self,
        tiers: dict[str, list[Provider]],
        *,
        router: Callable[[list[dict]], str] = default_router,
        cache_size: int = 256,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if "fast" not in tiers or "strong" not in tiers:
            raise ValueError("tiers must include 'fast' and 'strong'")
        self.tiers = tiers
        self._router = router
        self._cache: dict[str, tuple[Reply, str | None]] = {}
        self._cache_size = cache_size
        self._clock = clock
        self.stats = {p.name: ProviderStats() for ps in tiers.values() for p in ps}
        self.cache_hits = 0
        self.fallbacks = 0
        self.degraded = 0
        self._local = threading.local()  # last_provider / last_route are per thread, so visitors do not mix

    @property
    def last_provider(self) -> str | None:
        return getattr(self._local, "provider", None)

    @last_provider.setter
    def last_provider(self, value: str | None) -> None:
        self._local.provider = value

    @property
    def last_route(self) -> str | None:
        return getattr(self._local, "route", None)

    @last_route.setter
    def last_route(self, value: str | None) -> None:
        self._local.route = value

    @staticmethod
    def _key(messages: list[dict], tool_specs: list[dict]) -> str:
        blob = json.dumps([messages, tool_specs], sort_keys=True, default=lambda o: getattr(o, "__dict__", str(o)))
        return hashlib.sha256(blob.encode()).hexdigest()

    def _try_tier(self, tier: str, messages: list[dict], tool_specs: list[dict], errors: list) -> Reply | None:
        for index, provider in enumerate(self.tiers[tier]):
            st = self.stats[provider.name]
            if not provider.breaker.allow():
                st.skipped_open += 1  # no waiting on a provider we already know is down
                continue
            st.calls += 1
            start = self._clock()
            try:
                reply = call_with_timeout(lambda p=provider: p.model.next(messages, tool_specs), provider.timeout)
            except Exception as error:  # noqa: BLE001 - timeouts and provider errors both fall through
                st.failures += 1
                provider.breaker.record_failure()
                errors.append((provider.name, error))
                continue
            st.total_seconds += self._clock() - start
            provider.breaker.record_success()
            if index > 0 or errors:
                self.fallbacks += 1
            self.last_provider = provider.name
            return reply
        return None

    def next(self, messages: list[dict], tool_specs: list[dict]) -> Reply:
        key = self._key(messages, tool_specs)
        if key in self._cache:
            self.cache_hits += 1
            reply, made_by = self._cache[key]
            self.last_provider, self.last_route = f"{made_by} (cached)", "cache"
            return reply

        tier = self._router(messages)
        errors: list[tuple[str, BaseException]] = []
        reply = self._try_tier(tier, messages, tool_specs, errors)
        route = tier
        if reply is None and tier == "strong":
            reply = self._try_tier("fast", messages, tool_specs, errors)  # degrade rather than stop
            if reply is not None:
                self.degraded += 1
                route = "strong->fast (degraded)"
        if reply is None:
            raise AllProvidersFailed(errors)

        self.last_route = route
        if self._cache_size > 0:
            if len(self._cache) >= self._cache_size:
                self._cache.pop(next(iter(self._cache)))  # drop the oldest entry
            self._cache[key] = (reply, self.last_provider)
        return reply

    def report(self) -> dict:
        return {
            "providers": {
                n: {"calls": s.calls, "failures": s.failures, "skipped_open": s.skipped_open, "avg_seconds": round(s.avg_seconds, 4)}
                for n, s in self.stats.items()
            },
            "cache_hits": self.cache_hits,
            "fallbacks": self.fallbacks,
            "degraded": self.degraded,
        }

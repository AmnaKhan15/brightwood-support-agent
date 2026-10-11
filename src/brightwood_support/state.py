"""Shared, short-lived state in Redis: live sandboxes, rate limits, the daily AI budget, sign-in lockouts.

These are counters and timestamps that every server instance (and the background worker) must
agree on, which is what Redis is for. Production uses REDIS_URL (Upstash's free tier works).
Without it, an in-process fake Redis is used, so local runs and tests need nothing installed.

Times come from an injectable clock instead of Redis key expiry, so tests can move time forward.
"""
from __future__ import annotations

import secrets
from datetime import date
from typing import Callable

PREFIX = "bw:"


def redis_from_env(env):
    url = env.get("REDIS_URL", "")
    if url:
        import redis
        return redis.Redis.from_url(url, decode_responses=True, socket_timeout=5, health_check_interval=30)
    import fakeredis
    return fakeredis.FakeRedis(decode_responses=True)


class SandboxRegistry:
    """Which visitor sandboxes exist and when each was last used (a sorted set: id -> last-used time)."""

    KEY = PREFIX + "sandboxes"

    def __init__(self, r) -> None:
        self.r = r

    def touch(self, sid: str, now: float) -> None:
        self.r.zadd(self.KEY, {sid: now})

    def last_used(self, sid: str) -> float | None:
        return self.r.zscore(self.KEY, sid)

    def remove(self, sid: str) -> None:
        self.r.zrem(self.KEY, sid)

    def count(self) -> int:
        return int(self.r.zcard(self.KEY))

    def idle_since(self, cutoff: float) -> list[str]:
        return list(self.r.zrangebyscore(self.KEY, "-inf", cutoff))

    def oldest(self, n: int) -> list[str]:
        return list(self.r.zrange(self.KEY, 0, n - 1)) if n > 0 else []

    def all(self) -> list[str]:
        return list(self.r.zrange(self.KEY, 0, -1))


class RateLimiter:
    """A sliding window: at most `limit` events per `window` seconds per key."""

    def __init__(self, r, clock: Callable[[], float]) -> None:
        self.r, self._clock = r, clock

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = self._clock()
        k = PREFIX + "rl:" + key
        member = f"{now}:{secrets.token_hex(4)}"
        pipe = self.r.pipeline(transaction=True)  # one MULTI: concurrent callers all see each other's entries
        pipe.zremrangebyscore(k, "-inf", now - window)
        pipe.zadd(k, {member: now})
        pipe.zcard(k)
        pipe.expire(k, int(window) + 5)
        used = pipe.execute()[2]
        if used > limit:
            self.r.zrem(k, member)  # over the limit: this attempt does not count
            return False
        return True


class AiBudget:
    """A daily cap on real-model calls, shared by every server instance, so a free quota cannot be used up in one busy day."""

    def __init__(self, calls_per_day: int, today: Callable[[], date] = date.today, r=None) -> None:
        if r is None:
            import fakeredis
            r = fakeredis.FakeRedis(decode_responses=True)
        self.cap, self._today, self.r = calls_per_day, today, r

    def _key(self) -> str:
        return f"{PREFIX}ai_calls:{self._today().isoformat()}"

    @property
    def used(self) -> int:
        return int(self.r.get(self._key()) or 0)

    def take(self) -> bool:
        key = self._key()
        n = self.r.incr(key)
        if n == 1:
            self.r.expire(key, 2 * 86_400)
        if n > self.cap:
            self.r.decr(key)
            return False
        return True


def ping(r) -> bool:
    try:
        return bool(r.ping())
    except Exception:  # noqa: BLE001 - health reports it, nothing else depends on it
        return False

"""Shared, short-lived state in Redis: live sandboxes, rate limits, the daily AI budget, sign-in lockouts.

These are counters and timestamps that every server instance (and the background worker) must
agree on, which is what Redis is for. Production uses REDIS_URL (Upstash's free tier works).
Without it, an in-process fake Redis is used, so local runs and tests need nothing installed.

Times come from an injectable clock instead of Redis key expiry, so tests can move time forward.
"""
from __future__ import annotations

import secrets
import time
from datetime import date
from typing import Callable

PREFIX = "bw:"


def redis_from_env(env, backend=None):
    """REDIS_URL if set; otherwise the Postgres database when there is one (so serverless copies share state);
    otherwise an in-process fake for local runs and tests."""
    url = env.get("REDIS_URL", "")
    if url:
        import redis
        return redis.Redis.from_url(url, decode_responses=True, socket_timeout=5, health_check_interval=30)
    if backend is not None and getattr(backend, "persistent", False):
        return PgRedis(backend.main)
    import fakeredis
    return fakeredis.FakeRedis(decode_responses=True)


def _bound(v) -> float:
    return float(v)  # Redis bounds like "-inf" are valid Python floats too


class PgRedis:
    """The few Redis commands this app uses, stored in Postgres.

    Serverless hosts (Vercel) run many short-lived copies of the API with no shared memory, so sandboxes,
    rate limits and the AI budget must live somewhere shared. With no Redis, that is the database we
    already have. Sorted sets are rows of (key, member, score); strings are rows of (key, value, expiry).
    """

    def __init__(self, db, clock: Callable[[], float] = time.time, setup: bool = True) -> None:
        self.db, self._clock = db, clock
        if setup:
            db.script("""
                CREATE TABLE IF NOT EXISTS kv_zset(key TEXT NOT NULL, member TEXT NOT NULL, score DOUBLE PRECISION NOT NULL,
                                                   PRIMARY KEY(key, member));
                CREATE INDEX IF NOT EXISTS kv_zset_score ON kv_zset(key, score);
                CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at DOUBLE PRECISION);
                CREATE TABLE IF NOT EXISTS kv_ttl(key TEXT PRIMARY KEY, expires_at DOUBLE PRECISION NOT NULL);
            """)

    def _q(self, sql: str, params=()):
        return self.db.execute(sql, params)

    def _maybe_gc(self) -> None:
        if secrets.randbelow(50) == 0:  # now and then, drop keys whose expiry has passed
            now = self._clock()
            self._q("DELETE FROM kv_zset WHERE key IN (SELECT key FROM kv_ttl WHERE expires_at < ?)", (now,))
            self._q("DELETE FROM kv_ttl WHERE expires_at < ?", (now,))
            self._q("DELETE FROM kv WHERE expires_at < ?", (now,))

    # --- sorted sets ---
    def zadd(self, key: str, mapping: dict) -> int:
        for member, score in mapping.items():
            self._q("INSERT INTO kv_zset VALUES(?,?,?) ON CONFLICT(key, member) DO UPDATE SET score=excluded.score",
                    (key, str(member), float(score)))
        return len(mapping)

    def zscore(self, key: str, member: str) -> float | None:
        row = self._q("SELECT score FROM kv_zset WHERE key=? AND member=?", (key, member)).fetchone()
        return None if row is None else float(row["score"])

    def zrem(self, key: str, *members) -> int:
        for m in members:
            self._q("DELETE FROM kv_zset WHERE key=? AND member=?", (key, str(m)))
        return len(members)

    def zcard(self, key: str) -> int:
        return int(self._q("SELECT count(*) AS n FROM kv_zset WHERE key=?", (key,)).fetchone()["n"])

    def zrangebyscore(self, key: str, lo, hi) -> list[str]:
        rows = self._q("SELECT member FROM kv_zset WHERE key=? AND score>=? AND score<=? ORDER BY score, member",
                       (key, _bound(lo), _bound(hi))).fetchall()
        return [r["member"] for r in rows]

    def zremrangebyscore(self, key: str, lo, hi) -> int:
        self._q("DELETE FROM kv_zset WHERE key=? AND score>=? AND score<=?", (key, _bound(lo), _bound(hi)))
        return 0

    def zrange(self, key: str, start: int, end: int) -> list[str]:
        limit = "" if end == -1 else f" LIMIT {max(0, int(end) - int(start) + 1)}"
        rows = self._q(f"SELECT member FROM kv_zset WHERE key=? ORDER BY score, member{limit} OFFSET {int(start)}", (key,)).fetchall()
        return [r["member"] for r in rows]

    def expire(self, key: str, seconds: int) -> bool:
        until = self._clock() + seconds
        self._q("UPDATE kv SET expires_at=? WHERE key=?", (until, key))
        self._q("INSERT INTO kv_ttl VALUES(?,?) ON CONFLICT(key) DO UPDATE SET expires_at=excluded.expires_at", (key, until))
        self._maybe_gc()
        return True

    # --- strings ---
    def get(self, key: str) -> str | None:
        row = self._q("SELECT value FROM kv WHERE key=? AND (expires_at IS NULL OR expires_at>=?)", (key, self._clock())).fetchone()
        return None if row is None else row["value"]

    def _add(self, key: str, by: int) -> int:
        now = self._clock()
        row = self._q(
            "INSERT INTO kv VALUES(?,?,NULL) ON CONFLICT(key) DO UPDATE SET "
            "value=(CASE WHEN kv.expires_at IS NOT NULL AND kv.expires_at<? THEN 0 ELSE kv.value::bigint END + ?)::text, "
            "expires_at=CASE WHEN kv.expires_at IS NOT NULL AND kv.expires_at<? THEN NULL ELSE kv.expires_at END "
            "RETURNING value", (key, str(by), now, by, now)).fetchone()
        return int(row["value"])

    def incr(self, key: str) -> int:
        return self._add(key, 1)

    def decr(self, key: str) -> int:
        return self._add(key, -1)

    def set(self, key: str, value, nx: bool = False, ex: int | None = None) -> bool | None:
        now = self._clock()
        until = now + ex if ex else None
        if nx:  # only if absent (or expired)
            row = self._q("INSERT INTO kv VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at "
                          "WHERE kv.expires_at IS NOT NULL AND kv.expires_at<? RETURNING key", (key, str(value), until, now)).fetchone()
            return True if row else None
        self._q("INSERT INTO kv VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at",
                (key, str(value), until))
        return True

    def delete(self, *keys) -> int:
        for k in keys:
            self._q("DELETE FROM kv WHERE key=?", (k,))
            self._q("DELETE FROM kv_zset WHERE key=?", (k,))
        return len(keys)

    def exists(self, *keys) -> int:
        now = self._clock()
        return sum(1 for k in keys if self._q("SELECT 1 AS x FROM kv WHERE key=? AND (expires_at IS NULL OR expires_at>=?)", (k, now)).rows
                   or self._q("SELECT 1 AS x FROM kv_zset WHERE key=? LIMIT 1", (k,)).rows)

    def ping(self) -> bool:
        return bool(self._q("SELECT 1 AS x").rows)

    def pipeline(self, transaction: bool = True) -> "_PgPipeline":
        return _PgPipeline(self)


class _PgPipeline:
    """Queues commands and runs them in one database transaction, like Redis MULTI/EXEC.
    A per-key advisory lock makes concurrent pipelines on the same key take turns."""

    def __init__(self, store: PgRedis) -> None:
        self._store, self._calls = store, []

    def __getattr__(self, name: str):
        def queue(*args, **kwargs):
            self._calls.append((name, args, kwargs))
            return self
        return queue

    def execute(self) -> list:
        if not self._calls:
            return []
        with self._store.db.transaction() as tx:
            store = PgRedis(tx, self._store._clock, setup=False)
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (str(self._calls[0][1][0]),))
            out = [getattr(store, name)(*args, **kwargs) for name, args, kwargs in self._calls]
        self._calls = []
        return out


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

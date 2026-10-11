"""The run log: one row per assistant turn and per manager decision, kept across all sandboxes.

This is what the business metrics are computed from. Sandboxes are deleted after 30 minutes idle;
these rows are not. They hold no message text and no session id (only a one-way hash of it).

Outcome of a turn, from the customer's point of view:
  contained   answered without a person (state ok, refused or blocked, no ticket, no approval)
  escalated   a ticket was opened for a person
  approval    a refund is waiting for a manager
  failed      the run stopped early (step cap, cost cap, no model available)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import ID_COLUMN, Database, now_text, schema_for

# What "good" means for this assistant. Each target is checked by `summary()` and shown to staff.
TARGETS = {
    "containment_rate": (">=", 0.60, "share of conversations resolved without a person"),
    "failure_rate": ("<=", 0.02, "share of turns that stopped early (caps, no model)"),
    "p95_latency_ms": ("<=", 8000, "95th percentile time to answer"),
    "cost_per_conversation_usd": ("<=", 0.01, "model spend per turn, from tokens and MODEL_PRICE_PER_1K_TOKENS"),
    "median_approval_wait_s": ("<=", 4 * 3600, "how long a refund waits for a manager"),
}


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q from 0 to 1), or None for no values."""
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


class RunLog:
    def __init__(self, db: Database) -> None:
        self.db = db
        idc = ID_COLUMN[db.dialect]
        db.script(f"""
            CREATE TABLE IF NOT EXISTS agent_runs(id {idc}, sandbox TEXT NOT NULL, customer_id TEXT NOT NULL, agent TEXT,
              outcome TEXT NOT NULL, stopped TEXT NOT NULL, steps INTEGER NOT NULL, tokens INTEGER NOT NULL, millis INTEGER NOT NULL,
              provider TEXT, tools TEXT NOT NULL, rule_blocks INTEGER NOT NULL, injection_flag INTEGER NOT NULL,
              fell_back INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approval_decisions(id {idc}, sandbox TEXT NOT NULL, approval_id INTEGER NOT NULL,
              decision TEXT NOT NULL, role TEXT NOT NULL, wait_seconds REAL NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS agent_runs_created ON agent_runs(created_at);
            CREATE INDEX IF NOT EXISTS approval_decisions_created ON approval_decisions(created_at);
        """)

    @staticmethod
    def outcome(state: str, tools: list[str]) -> str:
        if state == "stopped":
            return "failed"
        if state == "waiting":
            return "approval"
        if "escalate_to_human" in tools:
            return "escalated"
        return "contained"

    def record_run(self, sid: str, customer: str, agent: str | None, state: str, stopped: str, steps: int, tokens: int,
                   millis: int, provider: str | None, tool_log: list[dict], injected: bool, fell_back: bool) -> None:
        tools = [t["tool"] for t in tool_log if t["status"] in ("ok", "pending_approval")]
        blocks = sum(1 for t in tool_log if t["status"] in ("refused", "rejected"))
        self.db.execute(
            "INSERT INTO agent_runs(sandbox, customer_id, agent, outcome, stopped, steps, tokens, millis, provider, tools, rule_blocks, "
            "injection_flag, fell_back, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (schema_for(sid), customer, agent, self.outcome(state, tools), stopped, steps, tokens, millis, provider,
             ",".join(t["tool"] for t in tool_log), blocks, int(injected), int(fell_back), now_text()))

    def record_decision(self, sid: str, approval_id: int, decision: str, role: str, wait_seconds: float) -> None:
        self.db.execute("INSERT INTO approval_decisions(sandbox, approval_id, decision, role, wait_seconds, created_at) VALUES(?,?,?,?,?,?)",
                        (schema_for(sid), approval_id, decision, role, max(0.0, wait_seconds), now_text()))

    def summary(self, days: int = 7, price_per_1k_tokens: float | None = None) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        runs = self.db.execute("SELECT agent, outcome, millis, tokens, rule_blocks, injection_flag, fell_back, provider "
                               "FROM agent_runs WHERE created_at >= ? ORDER BY id DESC LIMIT 5000", (since,)).fetchall()
        decisions = self.db.execute("SELECT decision, wait_seconds FROM approval_decisions WHERE created_at >= ?", (since,)).fetchall()
        n = len(runs)

        def share(outcome: str) -> float | None:
            return round(sum(1 for r in runs if r["outcome"] == outcome) / n, 4) if n else None

        tokens = [r["tokens"] for r in runs]
        avg_tokens = sum(tokens) / n if n else None
        values = {
            "conversations": n,
            "containment_rate": share("contained"),
            "escalation_rate": share("escalated"),
            "approval_rate": share("approval"),
            "failure_rate": share("failed"),
            "rule_blocks": sum(r["rule_blocks"] for r in runs),
            "injection_flags": sum(r["injection_flag"] for r in runs),
            "fallback_rate": round(sum(r["fell_back"] for r in runs) / n, 4) if n else None,
            "p50_latency_ms": percentile([r["millis"] for r in runs], 0.5),
            "p95_latency_ms": percentile([r["millis"] for r in runs], 0.95),
            "avg_tokens": round(avg_tokens, 1) if avg_tokens is not None else None,
            "cost_per_conversation_usd": round(avg_tokens / 1000 * price_per_1k_tokens, 6) if avg_tokens is not None and price_per_1k_tokens else None,
            "approvals_decided": len(decisions),
            "approvals_approved": sum(1 for d in decisions if d["decision"] == "approved"),
            "median_approval_wait_s": percentile([d["wait_seconds"] for d in decisions], 0.5),
            "by_agent": {a: sum(1 for r in runs if r["agent"] == a) for a in sorted({r["agent"] or "none" for r in runs})},
        }
        targets = []
        for key, (op, goal, meaning) in TARGETS.items():
            value = values.get(key)
            met = None if value is None else (value >= goal if op == ">=" else value <= goal)
            targets.append({"metric": key, "target": f"{op} {goal}", "value": value, "met": met, "meaning": meaning})
        return {"window_days": days, **values, "targets": targets}

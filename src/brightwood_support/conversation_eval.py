"""End-to-end conversation evals: real customer messages through the real service.

Each case in evals/conversations.json runs in a fresh sandbox, through the supervisor, the
specialists, the tools, the rules and the approval gate, with whatever model is configured (Gemini,
or the offline assistant). Then:

  - Code checks (always): the right specialist, the expected tools, no money moved when none
    should, no other customer's data or card number in the reply, a citation when policy is quoted.
  - Judges (optional, --judge): groundedness against the retrieved passages, correctness against
    the case's reference answer. See judges.py.

The same functions feed the fine-tuning pipeline, which keeps only trajectories that pass.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .runlog import percentile

CASES = Path(__file__).resolve().parents[2] / "evals" / "conversations.json"
CITATION = re.compile(r"\[[a-z_]+#[a-z0-9-]+\]")


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_case(service, case: dict) -> dict:
    """Play the case's turns in a fresh sandbox. Returns what happened on the last turn, plus side effects."""
    sid = service.create_session()
    started = time.perf_counter()
    result = None
    for turn in case["turns"]:
        result = service.chat(sid, case["customer"], turn)
    millis = round((time.perf_counter() - started) * 1000)
    inspect = result["inspect"]
    state = service.state(sid, case["customer"])
    context = "\n".join(f"[{r['id']}] {r['text']}" for r in inspect["retrieved"])
    tool_outputs = "\n".join(s["data"] for s in inspect["steps"] if s.get("status") == "ok" and s.get("tool") != "search_help")
    out = {
        "id": case["id"], "reply": result["reply"], "state": result["state"], "agent": inspect.get("agent"),
        "provider": inspect.get("provider"), "tokens": inspect["tokens"], "millis": millis,
        "fell_back": inspect["fell_back"],
        "tools": [(s["tool"], s["status"]) for s in inspect["steps"] if "tool" in s],
        "refunds": [r for r in state["refunds"] if r["customer_id"] == case["customer"]],
        "messages": [m["text"] for m in state["messages"]], "context": (context + "\n" + tool_outputs).strip(),
    }
    service._drop(sid)
    return out


def check(case: dict, out: dict) -> list[str]:
    """The code checks. An empty list means the case passed."""
    e, fails = case.get("expect", {}), []
    reply = (out["reply"] or "").lower()
    called = {name for name, _ in out["tools"]}
    succeeded = {name for name, status in out["tools"] if status in ("ok", "pending_approval")}
    if "agent" in e and out["agent"] not in (e["agent"], None):
        fails.append(f"routed to {out['agent']}, expected {e['agent']}")
    if "state" in e and out["state"] != e["state"]:
        fails.append(f"state {out['state']}, expected {e['state']}")
    if "state_any" in e and out["state"] not in e["state_any"]:
        fails.append(f"state {out['state']}, expected one of {e['state_any']}")
    for tool in e.get("tools_include", []):
        if tool not in called:
            fails.append(f"did not call {tool}")
    for tool in e.get("tools_exclude", []):
        if tool in succeeded:
            fails.append(f"{tool} ran but must not")
    if e.get("reply_any") and not any(s.lower() in reply for s in e["reply_any"]):
        fails.append(f"reply has none of {e['reply_any']}")
    for s in e.get("reply_none", []):
        if s.lower() in reply or any(s.lower() in m.lower() for m in out["messages"]):
            fails.append(f"leaked {s!r}")
    if e.get("cite") and not CITATION.search(out["reply"] or ""):
        fails.append("no [article#section] citation")
    if e.get("no_money") and out["refunds"]:
        fails.append(f"money moved: {[r['amount_cents'] for r in out['refunds']]}")
    return fails


def summarize(rows: list[dict], price_per_1k: float | None) -> dict:
    n = len(rows)
    lat = [r["millis"] for r in rows]
    tokens = [r["tokens"] for r in rows]
    summary = {
        "cases": n,
        "pass_rate": round(sum(1 for r in rows if not r["failures"]) / n, 4) if n else None,
        "p50_ms": percentile(lat, 0.5), "p95_ms": percentile(lat, 0.95),
        "avg_tokens": round(sum(tokens) / n, 1) if n else None,
        "cost_per_conversation_usd": round(sum(tokens) / n / 1000 * price_per_1k, 6) if n and price_per_1k else None,
        "fell_back_to_offline": sum(1 for r in rows if r["fell_back"]),
    }
    for judge in ("groundedness", "correctness"):
        scored = [r["judges"][judge]["score"] for r in rows if judge in r.get("judges", {})]
        if scored:
            summary[f"{judge}_rate"] = round(sum(scored) / len(scored), 4)
    return summary

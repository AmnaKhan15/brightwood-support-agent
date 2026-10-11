"""Decide whether a fine-tuned model may replace the base model: same evals, side by side.

    python finetune/compare.py --base gemini-2.5-flash-lite --candidate projects/P/locations/L/endpoints/E --candidate-vertex

Both models answer every case in evals/conversations.json (held out from training) through the real
agent. The candidate is adopted only if:
  - its code-check pass rate is at least the base model's (safety and behaviour do not regress),
  - its judge scores are no more than 2 points below (with --judge),
  - and it is cheaper per conversation (MODEL_PRICE_PER_1K_TOKENS_CANDIDATE vs MODEL_PRICE_PER_1K_TOKENS), or faster at p95.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from brightwood_support.conversation_eval import check, load_cases, run_case, summarize  # noqa: E402
from brightwood_support.service import Service  # noqa: E402


def evaluate(model: str, vertex: bool, price: float | None, judges) -> dict:
    env = {"DEMO_STAFF_LOGIN": "true", "SEMANTIC_SEARCH": "off", "GEMINI_MODEL": model, "GEMINI_STRONG_MODEL": model}
    if vertex:
        env.update({"GEMINI_USE_VERTEX": "true", "GOOGLE_CLOUD_PROJECT": os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
                    "GOOGLE_CLOUD_LOCATION": os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")})
    else:
        env["GEMINI_API_KEY"] = os.environ["GEMINI_API_KEY"]
    svc = Service(env=env, daily_ai_calls=100_000, per_minute=100_000)
    rows = []
    for case in load_cases():
        out = run_case(svc, case)
        out["failures"] = check(case, out)
        if judges:
            from brightwood_support.judges import grade
            out["judges"] = grade(judges, case["turns"][-1], out["reply"], out["context"], case.get("reference"))
        rows.append(out)
    return summarize(rows, price)


def decide(base: dict, cand: dict) -> list[str]:
    """Reasons to keep the base model. Empty means adopt the candidate."""
    reasons = []
    if (cand["pass_rate"] or 0) < (base["pass_rate"] or 0):
        reasons.append("lower code-check pass rate")
    for j in ("groundedness_rate", "correctness_rate"):
        if j in base and j in cand and cand[j] < base[j] - 0.02:
            reasons.append(f"{j} dropped")
    b_cost, c_cost = base.get("cost_per_conversation_usd"), cand.get("cost_per_conversation_usd")
    cheaper = b_cost is not None and c_cost is not None and c_cost < b_cost
    faster = (cand.get("p95_ms") or 0) < (base.get("p95_ms") or 0)
    if not (cheaper or faster):
        reasons.append("neither cheaper nor faster")
    return reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--candidate-vertex", action="store_true", help="the candidate is a tuned model served on Vertex AI")
    ap.add_argument("--judge", action="store_true")
    args = ap.parse_args()
    judges = None
    if args.judge:
        from brightwood_support.judges import build_judges, judge_model
        judges = build_judges(judge_model())
    base_price = float(os.environ["MODEL_PRICE_PER_1K_TOKENS"]) if os.environ.get("MODEL_PRICE_PER_1K_TOKENS") else None
    cand_price = float(os.environ["MODEL_PRICE_PER_1K_TOKENS_CANDIDATE"]) if os.environ.get("MODEL_PRICE_PER_1K_TOKENS_CANDIDATE") else base_price
    base = evaluate(args.base, False, base_price, judges)
    cand = evaluate(args.candidate, args.candidate_vertex, cand_price, judges)

    print(f"{'metric':<28}{'base':>14}{'candidate':>14}")
    for key in sorted(set(base) | set(cand)):
        print(f"{key:<28}{str(base.get(key)):>14}{str(cand.get(key)):>14}")
    reasons = decide(base, cand)
    verdict = {"adopt": not reasons, "reasons": reasons, "base": base, "candidate": cand}
    (ROOT / "finetune" / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "finetune" / "data" / "comparison.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print("\nADOPT the candidate" if not reasons else "\nKEEP the base model: " + "; ".join(reasons))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

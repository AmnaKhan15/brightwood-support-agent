"""Run the conversation evals. Exit code 1 if the pass rate is below the gate.

    python evals/run_conversation_eval.py                 # offline assistant, code checks only (what CI runs)
    python evals/run_conversation_eval.py --live --judge  # Gemini answers, a judge model grades quality
    python evals/run_conversation_eval.py --live --langsmith   # the same, recorded as a LangSmith experiment
    python evals/run_conversation_eval.py --calibrate     # how often the judge agrees with human labels

Live runs need GEMINI_API_KEY and GEMINI_MODEL (and JUDGE_MODEL for --judge); --langsmith needs LANGSMITH_API_KEY.
Reports go to evals/results/.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
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

KEYS_FOR_LIVE = ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_STRONG_MODEL", "GEMINI_EMBED_MODEL", "MODEL_PRICE_PER_1K_TOKENS", "SEMANTIC_SEARCH")


def make_service(live: bool) -> Service:
    env = {"DEMO_STAFF_LOGIN": "true", "SEMANTIC_SEARCH": "off"}
    if live:
        missing = [k for k in ("GEMINI_API_KEY", "GEMINI_MODEL") if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"--live needs {', '.join(missing)} (put them in .env)")
        env.update({k: os.environ[k] for k in KEYS_FOR_LIVE if os.environ.get(k)})
        env.setdefault("SEMANTIC_SEARCH", "on")
    # A large daily cap and rate limit: an eval run is a burst of traffic by design.
    return Service(env=env, daily_ai_calls=10_000, per_minute=10_000)


def calibrate() -> int:
    from brightwood_support.judges import build_judges, grade, judge_model

    judges = build_judges(judge_model())
    labelled = json.loads((ROOT / "evals" / "judge_calibration.json").read_text(encoding="utf-8"))
    agree = 0
    for ex in labelled:
        got = grade(judges, ex["question"], ex["answer"], ex["context"], None)["groundedness"]["score"]
        agree += got == ex["grounded"]
        print(("AGREE    " if got == ex["grounded"] else "DISAGREE ") + f"human={ex['grounded']} judge={got}  {ex['id']}")
    print(f"\njudge agreement with human labels: {agree}/{len(labelled)}")
    return 0 if agree / len(labelled) >= 0.85 else 1


def run_langsmith(service, cases: list[dict], judge: bool, live: bool) -> None:
    """Record the run as a LangSmith experiment over a versioned dataset, so runs can be compared side by side."""
    from langsmith import Client

    client = Client()
    name = "brightwood-support-conversations"
    if not client.has_dataset(dataset_name=name):
        ds = client.create_dataset(name, description="Brightwood support eval cases (evals/conversations.json)")
        client.create_examples(dataset_id=ds.id, examples=[
            {"inputs": {"customer": c["customer"], "turns": c["turns"]}, "outputs": {"reference": c.get("reference"), "case": c}} for c in cases])
    judges = None
    if judge:
        from brightwood_support.judges import build_judges, judge_model
        judges = build_judges(judge_model())

    def target(inputs: dict) -> dict:
        return run_case(service, {"id": "ls", "customer": inputs["customer"], "turns": inputs["turns"]})

    def code_checks(outputs: dict, reference_outputs: dict) -> dict:
        fails = check(reference_outputs["case"], outputs)
        return {"key": "code_checks", "score": not fails, "comment": "; ".join(fails)}

    evaluators = [code_checks]
    if judges:
        def groundedness(inputs: dict, outputs: dict) -> dict:
            r = judges["groundedness"](outputs=outputs["reply"], context=outputs["context"]) if outputs["context"] else {"score": True}
            return {"key": "groundedness", "score": bool(r["score"]), "comment": r.get("comment", "")}

        def correctness(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
            r = judges["correctness"](inputs=inputs["turns"][-1], outputs=outputs["reply"], reference_outputs=reference_outputs["reference"])
            return {"key": "correctness", "score": bool(r["score"]), "comment": r.get("comment", "")}
        evaluators += [groundedness, correctness]
    model = os.environ.get("GEMINI_MODEL", "offline") if live else "offline"
    client.evaluate(target, data=name, evaluators=evaluators, experiment_prefix=f"brightwood-{model}", max_concurrency=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use the configured Gemini model instead of the offline assistant")
    ap.add_argument("--judge", action="store_true", help="grade answers with the LLM judge (needs a key)")
    ap.add_argument("--langsmith", action="store_true", help="record the run as a LangSmith experiment")
    ap.add_argument("--calibrate", action="store_true", help="check the judge against human labels")
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--min-pass", type=float, default=0.80)
    args = ap.parse_args()
    if args.calibrate:
        return calibrate()

    cases = load_cases()
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only.split(","))]
    service = make_service(args.live)
    if args.langsmith:
        run_langsmith(service, cases, args.judge, args.live)
        return 0

    judges = None
    if args.judge:
        from brightwood_support.judges import build_judges, judge_model
        judges = build_judges(judge_model())
    rows = []
    for case in cases:
        out = run_case(service, case)
        out["failures"] = check(case, out)
        if judges:
            from brightwood_support.judges import grade
            out["judges"] = grade(judges, case["turns"][-1], out["reply"], out["context"], case.get("reference"))
        rows.append(out)
        bad = out["failures"] + [f"judge {k}: {v['comment'][:100]}" for k, v in out.get("judges", {}).items() if not v["score"]]
        print(("PASS " if not out["failures"] else "FAIL ") + f"{case['id']:<28} {out['agent'] or '-':<8} {out['provider'] or '-':<18} {out['millis']:>6} ms"
              + ("" if not bad else "  <- " + "; ".join(bad)))

    price = float(os.environ["MODEL_PRICE_PER_1K_TOKENS"]) if args.live and os.environ.get("MODEL_PRICE_PER_1K_TOKENS") else None
    summary = summarize(rows, price)
    print("\n" + json.dumps(summary, indent=2))
    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {"model": os.environ.get("GEMINI_MODEL") if args.live else "offline-assistant", "summary": summary,
              "cases": [{k: v for k, v in r.items() if k not in ("messages", "context")} for r in rows]}
    (out_dir / f"conversations_{'live' if args.live else 'offline'}_{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / f"conversations_{'live' if args.live else 'offline'}_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if summary["pass_rate"] is not None and summary["pass_rate"] < args.min_pass:
        print(f"GATE FAILED: pass rate {summary['pass_rate']:.2f} < {args.min_pass}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

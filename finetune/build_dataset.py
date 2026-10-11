"""Build the fine-tuning dataset from filtered teacher trajectories.

    python finetune/build_dataset.py --dry-run     # offline assistant as the "teacher": checks the pipeline, no key, no cost
    python finetune/build_dataset.py               # teacher = GEMINI_STRONG_MODEL (or GEMINI_MODEL); needs GEMINI_API_KEY

Writes finetune/data/{train,val}_{vertex,openai}.jsonl and manifest.json (counts, what was dropped and why).
The eval cases in evals/conversations.json are held out: overlapping prompts are never trained on.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from brightwood_support.agent import GENERALIST, SPECIALISTS, run_agent  # noqa: E402
from brightwood_support.conversation_eval import load_cases  # noqa: E402
from brightwood_support.finetune import keep, split, synthetic_prompts, to_openai, to_vertex  # noqa: E402
from brightwood_support.guardrails import mask_private  # noqa: E402
from brightwood_support.service import Service  # noqa: E402

OUT = ROOT / "finetune" / "data"


def teacher_service(dry_run: bool) -> tuple[Service, str]:
    env = {"DEMO_STAFF_LOGIN": "true", "SEMANTIC_SEARCH": "off"}
    if dry_run:
        return Service(env=env, daily_ai_calls=100_000, per_minute=100_000), "offline-assistant"
    teacher = os.environ.get("GEMINI_STRONG_MODEL") or os.environ.get("GEMINI_MODEL")
    if not (os.environ.get("GEMINI_API_KEY") and teacher):
        raise SystemExit("needs GEMINI_API_KEY and GEMINI_STRONG_MODEL (or GEMINI_MODEL), or use --dry-run")
    # The teacher answers every step: both gateway tiers use the strong model.
    env.update({"GEMINI_API_KEY": os.environ["GEMINI_API_KEY"], "GEMINI_MODEL": teacher, "GEMINI_STRONG_MODEL": teacher})
    return Service(env=env, daily_ai_calls=100_000, per_minute=100_000), teacher


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N prompts (for a cheap first run)")
    args = ap.parse_args()

    held_out = [t for c in load_cases() for t in c["turns"]]
    prompts, excluded = synthetic_prompts(held_out)
    if args.limit:
        prompts = prompts[: args.limit]
    svc, teacher = teacher_service(args.dry_run)
    kept, dropped = [], Counter()
    for p in prompts:
        sid = svc.create_session()
        s = svc.session(sid)
        toolbox, queue = s.customer(p["customer"])
        email = s.shop.customer_email(p["customer"])
        masker = lambda t, e=email: mask_private(t, keep_emails={e})  # noqa: E731
        result = run_agent(svc.gateway, toolbox, queue, p["turns"][0], mask=masker, max_steps=6, max_tokens=20_000, router=svc.router)
        reason = keep(p, result)
        svc._drop(sid)
        if reason:
            dropped[reason] += 1
            continue
        specs = toolbox.restricted(SPECIALISTS.get(result.agent, GENERALIST).tools).specs()
        kept.append({"vertex": to_vertex(result.messages, result.final_text, specs),
                     "openai": to_openai(result.messages, result.final_text, specs), "intent": p["intent"]})
        print(f"kept  [{result.agent}] {p['turns'][0]}")

    train, val = split(kept)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", train), ("val", val)):
        for fmt in ("vertex", "openai"):
            (OUT / f"{name}_{fmt}.jsonl").write_text("".join(json.dumps(r[fmt]) + "\n" for r in rows), encoding="utf-8")
    digest = hashlib.sha256((OUT / "train_vertex.jsonl").read_bytes()).hexdigest()[:16]
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "teacher": teacher, "dry_run": args.dry_run,
        "prompts": len(prompts), "excluded_for_eval_overlap": excluded, "kept": len(kept), "dropped": dict(dropped),
        "train": len(train), "val": len(val), "by_intent": dict(Counter(r["intent"] for r in kept)), "train_sha256_16": digest,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("\n" + json.dumps(manifest, indent=2))
    return 0 if kept else 1


if __name__ == "__main__":
    raise SystemExit(main())

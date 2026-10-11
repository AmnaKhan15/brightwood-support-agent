"""Run the retrieval eval and enforce the gate. Exit code 1 means a regression.

    python evals/run_retrieval_eval.py                 # word search (what CI gates on, no key needed)
    python evals/run_retrieval_eval.py --semantic      # hybrid: Gemini embeddings + words (needs GEMINI_API_KEY)
    python evals/run_retrieval_eval.py --k 3 --min-hit 0.85 --min-mrr 0.70

CI runs this on every push, so a change that makes retrieval worse blocks the
deploy. The corpus is synthetic (a fictional store), not customer data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brightwood_support.rag import (  # noqa: E402
    HashingEmbedder,
    InMemoryStore,
    evaluate,
    gate,
    load_corpus,
    semantic_from_env,
)


def build_retriever(store: InMemoryStore):
    return lambda query, k: [chunk.id for chunk, _ in store.search(query, k)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--min-hit", type=float, default=0.75)
    parser.add_argument("--min-mrr", type=float, default=0.70)
    parser.add_argument("--semantic", action="store_true", help="hybrid search with Gemini embeddings")
    args = parser.parse_args()

    semantic = None
    if args.semantic:
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
        except ImportError:
            pass
        import os
        semantic = semantic_from_env(os.environ)
        if semantic is None:
            raise SystemExit("--semantic needs GEMINI_API_KEY (put it in .env)")
    chunks = load_corpus(ROOT / "data" / "help")
    store = InMemoryStore(HashingEmbedder(), semantic)
    store.add(chunks)
    if args.semantic and store.mode != "hybrid":
        raise SystemExit("embedding the articles failed; see the warning above")
    cases = json.loads((ROOT / "evals" / "retrieval_cases.json").read_text(encoding="utf-8"))

    report = evaluate(build_retriever(store), cases, k=args.k)
    out = ROOT / "evals" / "results" / f"retrieval_{store.mode}_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"mode={store.mode} chunks={len(chunks)} cases={report['cases']} k={report['k']}")
    print(f"hit@{args.k}={report['hit_at_k']:.3f}  recall@{args.k}={report['recall_at_k']:.3f}  MRR={report['mrr']:.3f}")
    for miss in report["misses"]:
        print(f"MISS: {miss['question']!r} expected {miss['expected']} got {miss['retrieved']}")

    failures = gate(report, args.min_hit, args.min_mrr)
    for failure in failures:
        print(f"GATE FAILED: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

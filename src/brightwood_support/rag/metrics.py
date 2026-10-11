"""Retrieval metrics and the CI gate.

hit@k:    did at least one correct chunk appear in the top k?
recall@k: what share of the correct chunks appeared in the top k?
MRR:      mean of 1 / (rank of the first correct chunk); 0 if it never appears.
"""
from __future__ import annotations

from typing import Callable, Sequence

# A retriever takes (query, k) and returns chunk ids, best first.
Retriever = Callable[[str, int], Sequence[str]]


def evaluate(retrieve: Retriever, cases: list[dict], k: int = 3) -> dict:
    details = []
    for case in cases:
        expected = set(case["expected"])
        got = list(retrieve(case["question"], k))
        found = [cid for cid in got if cid in expected]
        rank = next((i + 1 for i, cid in enumerate(got) if cid in expected), None)
        details.append(
            {
                "question": case["question"],
                "expected": sorted(expected),
                "retrieved": got,
                "hit": bool(found),
                "recall": len(set(found)) / len(expected),
                "reciprocal_rank": 1.0 / rank if rank else 0.0,
            }
        )
    n = len(details)
    return {
        "k": k,
        "cases": n,
        "hit_at_k": sum(d["hit"] for d in details) / n if n else 0.0,
        "recall_at_k": sum(d["recall"] for d in details) / n if n else 0.0,
        "mrr": sum(d["reciprocal_rank"] for d in details) / n if n else 0.0,
        "misses": [d for d in details if not d["hit"]],
        "details": details,
    }


def gate(report: dict, min_hit: float, min_mrr: float) -> list[str]:
    """Return a list of failure messages. Empty means the gate passes."""
    failures = []
    if report["hit_at_k"] < min_hit:
        failures.append(f"hit@{report['k']} {report['hit_at_k']:.3f} is below {min_hit:.3f}")
    if report["mrr"] < min_mrr:
        failures.append(f"MRR {report['mrr']:.3f} is below {min_mrr:.3f}")
    return failures

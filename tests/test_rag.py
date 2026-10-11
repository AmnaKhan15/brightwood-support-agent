import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brightwood_support.rag import (  # noqa: E402
    HashingEmbedder,
    InMemoryStore,
    chunk_markdown,
    evaluate,
    gate,
    load_corpus,
)
from brightwood_support.rag.chunking import slug  # noqa: E402


class ChunkingTests(unittest.TestCase):
    def test_one_chunk_per_section_with_stable_ids(self):
        text = "# Title\n\n## Deductible\nPay $500.\n\n## Rental car\nUp to $40 a day.\n"
        chunks = chunk_markdown("auto", text)
        self.assertEqual([c.id for c in chunks], ["auto#deductible", "auto#rental-car"])
        self.assertEqual(chunks[0].text, "Pay $500.")

    def test_title_only_sections_are_skipped(self):
        self.assertEqual(chunk_markdown("d", "# Only a title\n"), [])

    def test_long_sections_are_split_and_ids_stay_unique(self):
        para = " ".join(["word"] * 80)
        text = f"## Big\n{para}\n\n{para}\n\n{para}\n"
        chunks = chunk_markdown("d", text, max_words=100)
        ids = [c.id for c in chunks]
        self.assertGreater(len(ids), 1)
        self.assertEqual(len(ids), len(set(ids)))

    def test_slug(self):
        self.assertEqual(slug("Filing a claim!"), "filing-a-claim")

    def test_corpus_loads_all_runbook_files(self):
        chunks = load_corpus(ROOT / "data" / "help")
        docs = {c.doc for c in chunks}
        self.assertEqual(len(docs), 12)
        self.assertEqual(len({c.id for c in chunks}), len(chunks))


class EmbeddingAndStoreTests(unittest.TestCase):
    def test_embedding_is_deterministic_and_unit_length(self):
        e = HashingEmbedder()
        a, b = e.embed("scale replicas"), e.embed("scale replicas")
        self.assertEqual(a, b)
        self.assertAlmostEqual(sum(x * x for x in a), 1.0, places=6)

    def test_empty_text_gives_zero_vector(self):
        self.assertEqual(sum(HashingEmbedder().embed("the of a")), 0.0)

    def test_search_returns_best_match_first_and_respects_k(self):
        store = InMemoryStore(HashingEmbedder())
        store.add(load_corpus(ROOT / "data" / "help"))
        results = store.search("How long is the return window?", k=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0].id, "returns#return-window")
        self.assertGreaterEqual(results[0][1], results[1][1])

    def test_search_on_empty_store(self):
        self.assertEqual(InMemoryStore(HashingEmbedder()).search("anything"), [])


class MetricsTests(unittest.TestCase):
    CASES = [
        {"question": "q1", "expected": ["a"]},
        {"question": "q2", "expected": ["b"]},
        {"question": "q3", "expected": ["c", "d"]},
    ]

    def test_metrics_on_a_known_retriever(self):
        answers = {"q1": ["a", "x"], "q2": ["x", "b"], "q3": ["x", "y"]}
        report = evaluate(lambda q, k: answers[q][:k], self.CASES, k=2)
        self.assertAlmostEqual(report["hit_at_k"], 2 / 3)
        self.assertAlmostEqual(report["mrr"], (1 + 0.5 + 0) / 3)
        self.assertAlmostEqual(report["recall_at_k"], (1 + 1 + 0) / 3)
        self.assertEqual(len(report["misses"]), 1)

    def test_recall_counts_partial_matches(self):
        report = evaluate(lambda q, k: ["c", "x"], [self.CASES[2]], k=2)
        self.assertAlmostEqual(report["recall_at_k"], 0.5)

    def test_gate_passes_and_fails(self):
        report = {"k": 3, "hit_at_k": 0.9, "mrr": 0.8}
        self.assertEqual(gate(report, 0.85, 0.7), [])
        self.assertEqual(len(gate(report, 0.95, 0.9)), 2)


class EvalGateTests(unittest.TestCase):
    """The shipped eval set must pass the shipped gate, or CI would be red."""

    def test_baseline_meets_the_default_gate(self):
        import json

        store = InMemoryStore(HashingEmbedder())
        store.add(load_corpus(ROOT / "data" / "help"))
        cases = json.loads((ROOT / "evals" / "retrieval_cases.json").read_text(encoding="utf-8"))
        known = {c.id for c in load_corpus(ROOT / "data" / "help")}
        for case in cases:  # every expected id must exist, or the eval is wrong
            self.assertTrue(set(case["expected"]) <= known, case)
        report = evaluate(lambda q, k: [c.id for c, _ in store.search(q, k)], cases, k=3)
        self.assertEqual(gate(report, 0.75, 0.70), [])


if __name__ == "__main__":
    unittest.main()

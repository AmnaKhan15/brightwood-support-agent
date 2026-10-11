"""A tiny in-memory vector store.

It has the same shape a real vector database needs: add chunks, search by a
query. A pgvector-on-RDS store replaces it later behind the same two methods,
so the agent and the evals do not change.
"""
from __future__ import annotations

from .chunking import Chunk
from .embeddings import Embedder


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class InMemoryStore:
    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            # The heading is part of the meaning of a rule, so embed it too.
            self._vectors.append(self.embedder.embed(f"{chunk.heading}. {chunk.text}"))
            self._chunks.append(chunk)

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        """Return the top-k (chunk, cosine score) pairs, best first."""
        if not self._chunks:
            return []
        q = self.embedder.embed(query)
        scored = [(c, _dot(q, v)) for c, v in zip(self._chunks, self._vectors)]
        # Sort by score, then id, so ties always come out in the same order.
        scored.sort(key=lambda pair: (-pair[1], pair[0].id))
        return scored[:k]

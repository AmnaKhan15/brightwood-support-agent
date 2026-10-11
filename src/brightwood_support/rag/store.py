"""Vector stores for the help articles. Both have the same two methods: add chunks, search by a query.

  - InMemoryStore   exact search in Python. Used by tests, evals and local runs.
  - PgVectorStore   the chunks and their vectors in Postgres (pgvector), shared by every visitor
                    and every server instance. Used when DATABASE_URL points at Postgres.

Each keeps two vectors per chunk: a word vector (always) and a semantic vector (when an embedding
model is configured). Search ranks by the hybrid score in semantic.py. If the embedding model fails
for a query, that query falls back to word matching instead of failing.
"""
from __future__ import annotations

import hashlib
import json
import logging

from .chunking import Chunk
from .embeddings import Embedder
from .semantic import SemanticEmbedder, hybrid

log = logging.getLogger(__name__)


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _text(chunk: Chunk) -> str:
    # The heading is part of the meaning of a rule, so embed it too.
    return f"{chunk.heading}. {chunk.text}"


def _semantic_query(semantic: SemanticEmbedder | None, query: str) -> list[float] | None:
    """The query's meaning vector, or None (no model, or the model failed: search falls back to words)."""
    if semantic is None:
        return None
    try:
        return semantic.embed_query(query)
    except Exception as error:  # noqa: BLE001
        log.warning("semantic query failed, falling back to words: %r", error)
        return None


def _ranked(scored: list[tuple[Chunk, float]], k: int) -> list[tuple[Chunk, float]]:
    # Sort by score, then id, so ties always come out in the same order.
    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    return scored[:k]


class _Chunks:
    _chunks: list[Chunk]

    def __len__(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> list[Chunk]:
        return list(self._chunks)


class InMemoryStore(_Chunks):
    def __init__(self, embedder: Embedder, semantic: SemanticEmbedder | None = None) -> None:
        self.embedder = embedder
        self.semantic = semantic
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []
        self._semantic_vectors: list[list[float]] | None = [] if semantic else None

    @property
    def mode(self) -> str:
        return "hybrid" if self._semantic_vectors is not None else "words"

    def add(self, chunks: list[Chunk]) -> None:
        if self._semantic_vectors is not None:
            try:
                self._semantic_vectors += self.semantic.embed_documents([_text(c) for c in chunks])
            except Exception as error:  # noqa: BLE001 - search still works on words alone
                log.warning("semantic embeddings unavailable, using word search only: %r", error)
                self._semantic_vectors = None
        for chunk in chunks:
            self._vectors.append(self.embedder.embed(_text(chunk)))
            self._chunks.append(chunk)

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        """Return the top-k (chunk, score) pairs, best first."""
        if not self._chunks:
            return []
        q = self.embedder.embed(query)
        qs = _semantic_query(self.semantic if self._semantic_vectors is not None else None, query)
        scored = []
        for i, (c, v) in enumerate(zip(self._chunks, self._vectors)):
            cosine = _dot(qs, self._semantic_vectors[i]) if qs is not None else None
            scored.append((c, hybrid(_dot(q, v), cosine)))
        return _ranked(scored, k)


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class PgVectorStore(_Chunks):
    """Help-article chunks in Postgres with pgvector. Re-embeds only when the articles or the model change."""

    def __init__(self, db, embedder: Embedder, semantic: SemanticEmbedder | None = None) -> None:
        self.db, self.embedder, self.semantic = db, embedder, semantic
        self._chunks: list[Chunk] = []
        self._has_semantic = False
        sem_dim = semantic.dim if semantic else 768
        db.script(f"""
            CREATE TABLE IF NOT EXISTS help_chunks(
              id TEXT PRIMARY KEY, doc TEXT NOT NULL, heading TEXT NOT NULL, text TEXT NOT NULL,
              word_vec vector({embedder.dim}) NOT NULL, semantic_vec vector({sem_dim}));
            CREATE TABLE IF NOT EXISTS help_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        # No ANN index: with a few dozen chunks an exact scan is faster and exact. Add an HNSW index
        # (vector_cosine_ops) on semantic_vec once the corpus grows past a few thousand chunks.

    @property
    def mode(self) -> str:
        return "hybrid (pgvector)" if self._has_semantic else "words (pgvector)"

    def _fingerprint(self, chunks: list[Chunk]) -> str:
        blob = json.dumps([[c.id, c.heading, c.text] for c in chunks]) + "|" + (getattr(self.semantic, "model", "") or "none")
        return hashlib.sha256(blob.encode()).hexdigest()

    def add(self, chunks: list[Chunk]) -> None:
        self._chunks = list(chunks)
        fp = self._fingerprint(chunks)
        row = self.db.execute("SELECT value FROM help_meta WHERE key='fingerprint'").fetchone()
        if row and row["value"] == fp:
            self._has_semantic = bool(self.db.execute("SELECT 1 AS x FROM help_chunks WHERE semantic_vec IS NOT NULL LIMIT 1").rows)
            log.info("help index up to date (%d chunks)", len(chunks))
            return
        semantic_vecs = None
        if self.semantic:
            try:
                semantic_vecs = self.semantic.embed_documents([_text(c) for c in chunks])
            except Exception as error:  # noqa: BLE001
                log.warning("semantic embeddings unavailable, indexing words only: %r", error)
        with self.db.transaction() as tx:  # other instances keep seeing the old index until this commits
            tx.execute("DELETE FROM help_chunks")
            for i, c in enumerate(chunks):
                tx.execute("INSERT INTO help_chunks VALUES(?,?,?,?,?::vector,?::vector)",
                           (c.id, c.doc, c.heading, c.text, _vec(self.embedder.embed(_text(c))),
                            _vec(semantic_vecs[i]) if semantic_vecs else None))
            tx.execute("INSERT INTO help_meta VALUES('fingerprint', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (fp if semantic_vecs or not self.semantic else "partial",))
        self._has_semantic = semantic_vecs is not None
        log.info("help index rebuilt (%d chunks, semantic=%s)", len(chunks), self._has_semantic)

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        if not self._chunks:
            return []
        qw = self.embedder.embed(query)
        if not any(qw):
            return [(c, 0.0) for c in sorted(self._chunks, key=lambda c: c.id)[:k]]
        qs = _semantic_query(self.semantic if self._has_semantic else None, query)
        by_id = {c.id: c for c in self._chunks}
        # pgvector's <=> is cosine distance, so 1 - distance is cosine similarity (NULL when the query has no
        # meaning vector). Postgres computes the similarities; the hybrid score is applied in Python so both
        # stores rank identically.
        rows = self.db.execute(
            "SELECT id, 1 - (word_vec <=> ?::vector) AS word, 1 - (semantic_vec <=> ?::vector) AS sem FROM help_chunks",
            (_vec(qw), _vec(qs) if qs is not None else None)).fetchall()
        scored = []
        for r in rows:
            word = 0.0 if r["word"] is None or r["word"] != r["word"] else float(r["word"])  # NaN for an all-zero vector
            sem = None if r["sem"] is None else float(r["sem"])
            if r["id"] in by_id:
                scored.append((by_id[r["id"]], hybrid(word, sem)))
        return _ranked(scored, k)

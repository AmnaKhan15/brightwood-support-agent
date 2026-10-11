"""Semantic embeddings and the hybrid score.

Word matching (HashingEmbedder) misses synonyms: "broken" does not find "damaged", "charged twice"
does not find "double charge". A model embedding captures meaning, but on its own it can rank a
passage that merely sounds related above one with the exact words. The hybrid score blends both.

Scale: Gemini cosine scores for unrelated text sit around 0.45-0.55 and close matches around 0.8,
while the word score is 0 for no shared words. `semantic_scaled` maps the model score onto 0..1 so
the two can be blended and the offline assistant's relevance threshold keeps its meaning.
SEMANTIC_FLOOR is a calibration constant: check it with `evals/run_retrieval_eval.py --semantic`.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Protocol

from .embeddings import normalize

log = logging.getLogger(__name__)

WORD_WEIGHT = 0.4
SEMANTIC_WEIGHT = 0.6
SEMANTIC_FLOOR = 0.45
DIM = 768


class SemanticEmbedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def semantic_scaled(cosine: float) -> float:
    return min(1.0, max(0.0, (cosine - SEMANTIC_FLOOR) / (1 - SEMANTIC_FLOOR)))


def hybrid(word: float, cosine: float | None) -> float:
    if cosine is None:
        return word
    return WORD_WEIGHT * max(0.0, word) + SEMANTIC_WEIGHT * semantic_scaled(cosine)


class GeminiEmbedder:
    """Gemini embeddings through LangChain, with a small cache so a repeated question costs nothing."""

    def __init__(self, api_key: str, model: str = "models/gemini-embedding-001", dim: int = DIM, client=None) -> None:
        if client is None:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            client = GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key, request_options={"timeout": 10})
        self._client, self.dim, self.model = client, dim, model
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = self._client.embed_documents(texts, task_type="RETRIEVAL_DOCUMENT", output_dimensionality=self.dim)
        return [normalize(v) for v in vecs]

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            if text in self._cache:
                self._cache.move_to_end(text)
                return self._cache[text]
        vec = normalize(self._client.embed_query(text, task_type="RETRIEVAL_QUERY", output_dimensionality=self.dim))
        with self._lock:
            self._cache[text] = vec
            if len(self._cache) > 512:
                self._cache.popitem(last=False)
        return vec


def semantic_from_env(env) -> SemanticEmbedder | None:
    if env.get("GEMINI_API_KEY") and env.get("SEMANTIC_SEARCH", "on") != "off":
        return GeminiEmbedder(env["GEMINI_API_KEY"], env.get("GEMINI_EMBED_MODEL", "models/gemini-embedding-001"))
    return None

"""Embedders turn text into vectors so we can compare meaning by cosine similarity.

HashingEmbedder is a baseline that needs no model, key or network. It hashes
words and word pairs into a fixed-size vector (the "hashing trick"). It matches
on shared words, not on meaning, so it is the number to beat. A model-based
embedder plugs in behind the same two-method interface on a later day.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i if in is it my of on or "
    "our so than that the their then there these they this to was we what when "
    "which who will with you your".split()
)


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


def _stem(word: str) -> str:
    """Very light stemming so "returns" and "return" share a feature."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


class HashingEmbedder:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        words = [_stem(t) for t in tokens(text)]
        features = [(w, 1.0) for w in words]
        features += [(f"{a}_{b}", 0.5) for a, b in zip(words, words[1:])]
        vec = [0.0] * self.dim
        for feature, weight in features:
            digest = int(hashlib.md5(feature.encode()).hexdigest(), 16)
            index = digest % self.dim
            sign = 1.0 if (digest >> 64) & 1 else -1.0
            vec[index] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

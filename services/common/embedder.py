"""Embedders behind one interface (spec section 5; W2 design section 3).

W2 ships HashEmbedder, a deterministic fake whose similarity is real token
overlap: each token hashes to a fixed pseudo-random unit vector and a text is
the normalized sum of its token vectors. Paraphrases sharing vocabulary score
high, unrelated text scores near zero — an honest miniature of an embedding
model, not a rigged lookup. Bedrock Titan lands behind the same protocol in W3.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

DIMENSIONS = 1024

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


@lru_cache(maxsize=4096)
def _token_vector(token: str) -> tuple[float, ...]:
    """Deterministic pseudo-random unit vector for one token.

    Expands SHA-256 over (namespaced token, counter) into DIMENSIONS uniform
    floats in [-1, 1), then L2-normalizes. Stable across runs and platforms.
    """
    seed = hashlib.sha256(b"recant-hash-embedder:" + token.encode()).digest()
    values: list[float] = []
    counter = 0
    while len(values) < DIMENSIONS:
        block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for i in range(0, 32, 4):
            values.append(int.from_bytes(block[i : i + 4], "big") / 2**31 - 1.0)
        counter += 1
    values = values[:DIMENSIONS]
    norm = math.sqrt(sum(v * v for v in values))
    return tuple(v / norm for v in values)


class HashEmbedder:
    # Lexical-overlap scale: measured paraphrases score ~0.5-0.6, unrelated
    # text < 0.11 (docs/plans/2026-07-03-week2.md section 3). Titan's default
    # will be 0.80 on the semantic scale.
    default_threshold = 0.35

    def embed(self, text: str) -> list[float]:
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            raise ValueError("cannot embed text with no alphanumeric tokens")
        acc = [0.0] * DIMENSIONS
        for token in tokens:
            vec = _token_vector(token)
            for i in range(DIMENSIONS):
                acc[i] += vec[i]
        norm = math.sqrt(sum(v * v for v in acc))
        return [v / norm for v in acc]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))

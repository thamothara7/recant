"""Embedders behind one interface (spec section 5; W2 design section 3).

W2 ships HashEmbedder, a deterministic fake whose similarity is real token
overlap: each token hashes to a fixed pseudo-random unit vector and a text is
the normalized sum of its token vectors. Paraphrases sharing vocabulary score
high, unrelated text scores near zero, an honest miniature of an embedding
model, not a rigged lookup. Bedrock Titan lands behind the same protocol in W3.

Selection is env-driven (RECANT_EMBEDDER): 'hash' stays the default so the
deterministic story seed, the demo, and the test suite are reproducible;
'titan' switches the fleet write path to Bedrock Titan Text Embeddings V2 for
cloud runs. The taint engine never re-embeds text (it compares stored vectors),
so the only cross-cutting concern is the similarity threshold, which tracks the
selected embedder via active_threshold().
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache
from typing import Protocol

DIMENSIONS = 1024

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    default_threshold: float

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


class TitanEmbedder:
    """Bedrock Titan Text Embeddings V2 (decision 3), 1024-dim, L2-normalized.

    Normalized output means cosine similarity equals the dot product, matching
    the VECTOR(1024) column and the cosine index (decision 8). The boto3 client
    is constructed lazily and cached so importing this module never touches AWS
    (tests inject a fake client); only embed() reaches Bedrock. Region comes from
    the standard AWS env (AWS_REGION / AWS_DEFAULT_REGION), defaulting us-east-1
    to align with the cluster and the fanout path (decision 22).
    """

    # Semantic-scale threshold, provisional. A live probe of Titan V2 (Jul 16,
    # 4 paraphrase pairs vs 3 unrelated) put paraphrases at 0.34-0.50 (min 0.338)
    # and unrelated at 0.02-0.05 (max 0.046): a wide, clean gap. 0.30 catches
    # every paraphrase and rejects every unrelated pair with ~6x margin. It still
    # needs validation against the seed story's "same topic, different claim"
    # cases (decision 9), which score higher than truly-unrelated text;
    # RECANT_TAINT_THRESHOLD overrides, and check_story() is the harness.
    default_threshold = 0.30

    MODEL_ID = os.environ.get("RECANT_TITAN_MODEL", "amazon.titan-embed-text-v2:0")

    def __init__(self, client=None):
        self._client = client

    def _bedrock(self):
        if self._client is None:
            import boto3

            region = (
                os.environ.get("AWS_REGION")
                or os.environ.get("AWS_DEFAULT_REGION")
                or "us-east-1"
            )
            self._client = boto3.client("bedrock-runtime", region_name=region)
        return self._client

    def embed(self, text: str) -> list[float]:
        if not _TOKEN_RE.search(text.lower()):
            raise ValueError("cannot embed text with no alphanumeric tokens")
        import json

        resp = self._bedrock().invoke_model(
            modelId=self.MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {"inputText": text, "dimensions": DIMENSIONS, "normalize": True}
            ),
        )
        payload = json.loads(resp["body"].read())
        vector = payload["embedding"]
        if len(vector) != DIMENSIONS:
            raise ValueError(
                f"Titan returned {len(vector)} dims, expected {DIMENSIONS}"
            )
        return vector


_EMBEDDERS: dict[str, type] = {"hash": HashEmbedder, "titan": TitanEmbedder}


def select_embedder() -> Embedder:
    """Construct the embedder named by RECANT_EMBEDDER (default 'hash').

    Single source of truth for both the fleet write path and any other caller;
    constructing TitanEmbedder does not touch AWS (the client is lazy).
    """
    name = os.environ.get("RECANT_EMBEDDER", "hash")
    try:
        return _EMBEDDERS[name]()
    except KeyError:
        raise ValueError(f"unknown RECANT_EMBEDDER: {name!r}") from None


def active_threshold() -> float:
    """Similarity threshold for the selected embedder.

    RECANT_TAINT_THRESHOLD overrides everything; otherwise the value tracks the
    selected embedder's class default without constructing it (so reading the
    threshold never builds a Bedrock client).
    """
    env = os.environ.get("RECANT_TAINT_THRESHOLD")
    if env:
        return float(env)
    name = os.environ.get("RECANT_EMBEDDER", "hash")
    cls = _EMBEDDERS.get(name, HashEmbedder)
    return cls.default_threshold


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))

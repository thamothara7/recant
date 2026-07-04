"""taint-engine: computes the contamination closure of a source (spec section 5).

Explicit closure walks derivations with a recursive CTE (kind-agnostic: explicit
write-path edges and inferred edges materialized by earlier recants both carry
taint). Implicit closure probes the cosine vector index with top-K kNN per newly
tainted belief. The two alternate to a fixpoint.

compute_closure runs on a caller-provided connection so the quarantine service
executes it INSIDE its serializable transaction: the closure that gets flipped is
the closure that was computed, with no gap for concurrent writes to slip through.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import psycopg

from services.common.embedder import HashEmbedder

KNN_TOP_K = int(os.environ.get("RECANT_TAINT_TOP_K", "20"))
KNN_MAX_K = int(os.environ.get("RECANT_TAINT_MAX_K", "320"))
MAX_ROUNDS = 10

# Statuses a kNN hit may hold to join the closure as a new member. Quarantined
# hits are already handled; retracted beliefs are never resurrected.
_TAINTABLE = ("active", "suspect")


def default_threshold() -> float:
    env = os.environ.get("RECANT_TAINT_THRESHOLD")
    return float(env) if env else HashEmbedder.default_threshold


@dataclass
class InferredEdge:
    child_id: UUID
    parent_id: UUID
    score: float


@dataclass
class Closure:
    source_id: UUID
    seed_ids: list[UUID]
    member_ids: list[UUID]
    inferred_edges: list[InferredEdge]
    window_start: datetime | None
    rounds: int
    knn_ms: int
    threshold: float
    # Two distinct incompleteness signals, kept separate so the operator log and
    # the console preview point at the right knob (review 2026-07-03):
    #   rounds_capped  -> the 10-round runaway guard fired (tune MAX_ROUNDS)
    #   knn_truncated  -> a kNN boundary was still hot at max_k (tune RECANT_TAINT_MAX_K)
    rounds_capped: bool = False
    knn_truncated: bool = False
    agent_ids: list[UUID] = field(default_factory=list)


def _explicit_descendants(conn: psycopg.Connection, frontier: list[UUID]) -> set[UUID]:
    rows = conn.execute(
        """
        WITH RECURSIVE tainted (belief_id) AS (
            SELECT belief_id FROM beliefs WHERE belief_id = ANY(%s)
            UNION
            SELECT d.child_id FROM derivations d JOIN tainted t ON d.parent_id = t.belief_id
        )
        SELECT belief_id FROM tainted
        """,
        (frontier,),
    ).fetchall()
    return {r[0] for r in rows}


def _knn_query(
    conn: psycopg.Connection,
    probe_embedding_text: str,
    k: int,
) -> list[tuple[UUID, str, datetime, float]]:
    """Top-K by cosine distance. Deliberately no WHERE clause: the bare
    ORDER BY + LIMIT shape is what the vector index serves (design section 1);
    every filter happens in the caller."""
    rows = conn.execute(
        """
        SELECT belief_id, status, created_at, embedding <=> %s::vector AS dist
        FROM beliefs
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (probe_embedding_text, probe_embedding_text, k),
    ).fetchall()
    return [(r[0], r[1], r[2], float(r[3])) for r in rows if r[3] is not None]


def _knn_hits(
    conn: psycopg.Connection,
    probe_embedding_text: str,
    *,
    top_k: int,
    max_k: int,
    threshold: float,
) -> tuple[list[tuple[UUID, str, datetime, float]], bool]:
    """Adaptive K: post-LIMIT filtering must not cap recall. If the farthest
    returned neighbor still clears the threshold, there may be more beyond it —
    double K and retry, bounded by max_k. Returns (hits, truncated): truncated
    means the boundary was still hot at max_k (design review 2026-07-03)."""
    k = top_k
    while True:
        hits = _knn_query(conn, probe_embedding_text, k)
        exhausted = len(hits) < k
        boundary_hot = bool(hits) and (1.0 - hits[-1][3]) >= threshold
        if exhausted or not boundary_hot:
            return hits, False
        if k >= max_k:
            return hits, True
        k = min(k * 2, max_k)


def compute_closure(
    conn: psycopg.Connection,
    source_id: UUID,
    *,
    threshold: float | None = None,
    top_k: int | None = None,
    max_k: int | None = None,
    max_rounds: int | None = None,
) -> Closure:
    # Late-bound so tests can patch the module attributes.
    threshold = default_threshold() if threshold is None else threshold
    top_k = KNN_TOP_K if top_k is None else top_k
    max_k = KNN_MAX_K if max_k is None else max_k
    max_rounds = MAX_ROUNDS if max_rounds is None else max_rounds

    seed_rows = conn.execute(
        "SELECT belief_id, created_at FROM beliefs WHERE source_id = %s",
        (source_id,),
    ).fetchall()
    seed_ids = [r[0] for r in seed_rows]

    # Window anchor: when the source ENTERED the system, not its first recorded
    # citation — an unrecorded paraphrase can predate the first explicit seed
    # (design review 2026-07-03). LEAST with the seed minimum for safety.
    src_row = conn.execute(
        "SELECT created_at FROM sources WHERE source_id = %s", (source_id,)
    ).fetchone()
    candidates = [r[1] for r in seed_rows] + ([src_row[0]] if src_row else [])
    window_start = min(candidates, default=None)

    closure: set[UUID] = set(seed_ids)
    inferred_edges: list[InferredEdge] = []
    probed: set[UUID] = set()
    frontier: list[UUID] = list(seed_ids)
    knn_ms = 0.0
    rounds = 0
    rounds_capped = False
    knn_truncated = False

    while frontier:
        if rounds >= max_rounds:
            rounds_capped = True
            break
        rounds += 1

        explicit = _explicit_descendants(conn, frontier) - closure if frontier else set()
        closure |= explicit
        to_probe = [b for b in (set(frontier) | explicit) if b not in probed]
        probed |= set(to_probe)

        implicit: set[UUID] = set()
        if to_probe:
            emb_rows = conn.execute(
                "SELECT belief_id, embedding::text FROM beliefs"
                " WHERE belief_id = ANY(%s) AND embedding IS NOT NULL",
                (to_probe,),
            ).fetchall()
            t0 = time.perf_counter()
            # Best-parent-wins per hit within the round: when several probes match
            # the same new belief, record the single edge to the HIGHEST-similarity
            # probe, not whichever the (unordered) scan returned first (review
            # 2026-07-03). Buffer, then commit the winners to the closure.
            best: dict[UUID, tuple[UUID, float]] = {}
            for probe_id, emb_text in emb_rows:
                hits, truncated = _knn_hits(
                    conn, emb_text, top_k=top_k, max_k=max_k, threshold=threshold
                )
                if truncated:
                    knn_truncated = True
                for hit_id, status, created_at, dist in hits:
                    similarity = 1.0 - dist
                    if (
                        hit_id == probe_id
                        or hit_id in closure
                        or similarity < threshold
                        or status not in _TAINTABLE
                        or (window_start is not None and created_at < window_start)
                    ):
                        continue
                    current = best.get(hit_id)
                    if current is None or similarity > current[1]:
                        best[hit_id] = (probe_id, similarity)
            knn_ms += (time.perf_counter() - t0) * 1000
            for hit_id in sorted(best, key=str):
                parent_id, similarity = best[hit_id]
                implicit.add(hit_id)
                closure.add(hit_id)
                inferred_edges.append(
                    InferredEdge(child_id=hit_id, parent_id=parent_id, score=round(similarity, 4))
                )

        frontier = sorted(explicit | implicit, key=str)

    member_ids = sorted(closure, key=str)
    agent_ids: list[UUID] = []
    if member_ids:
        agent_ids = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT agent_id FROM beliefs WHERE belief_id = ANY(%s)",
                (member_ids,),
            ).fetchall()
        ]

    return Closure(
        source_id=source_id,
        seed_ids=sorted(seed_ids, key=str),
        member_ids=member_ids,
        inferred_edges=inferred_edges,
        window_start=window_start,
        rounds=rounds,
        knn_ms=int(knn_ms),
        threshold=threshold,
        rounds_capped=rounds_capped,
        knn_truncated=knn_truncated,
        agent_ids=sorted(agent_ids, key=str),
    )

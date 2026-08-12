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

from services.common.auth import DEFAULT_TENANT_ID
from services.common.embedder import active_threshold

KNN_TOP_K = int(os.environ.get("RECANT_TAINT_TOP_K", "20"))
KNN_MAX_K = int(os.environ.get("RECANT_TAINT_MAX_K", "320"))
MAX_ROUNDS = 10

# Statuses a kNN hit may hold to join the closure as a new member. Quarantined
# hits are already handled; retracted beliefs are never resurrected.
_TAINTABLE = ("active", "suspect")


def default_threshold() -> float:
    # Tracks the selected embedder (RECANT_EMBEDDER); RECANT_TAINT_THRESHOLD
    # overrides. The taint engine compares stored vectors and never re-embeds,
    # so only this threshold constant depends on the embedding model.
    return active_threshold()


@dataclass
class InferredEdge:
    child_id: UUID
    parent_id: UUID
    score: float
    evidence_method: str = "vector_similarity"
    evidence_model: str | None = None
    evidence_version: str = "v1"


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


def _explicit_descendants(
    conn: psycopg.Connection, frontier: list[UUID], tenant_id: UUID
) -> set[UUID]:
    rows = conn.execute(
        """
        WITH RECURSIVE tainted (belief_id) AS (
            SELECT belief_id FROM beliefs WHERE tenant_id = %s AND belief_id = ANY(%s)
            UNION
            SELECT d.child_id FROM derivations d JOIN tainted t ON d.parent_id = t.belief_id
            WHERE d.tenant_id = %s
        )
        SELECT belief_id FROM tainted
        """,
        (tenant_id, frontier, tenant_id),
    ).fetchall()
    return {r[0] for r in rows}


def _knn_query(
    conn: psycopg.Connection,
    probe_embedding_text: str,
    k: int,
    tenant_id: UUID,
) -> list[tuple[UUID, str, datetime, UUID | None, UUID, str, float]]:
    """Top-K by cosine distance within a vector-index tenant prefix."""
    rows = conn.execute(
        """
        SELECT belief_id, status, created_at, source_id, tenant_id, content,
               embedding <=> %s::vector AS dist
        FROM beliefs@beliefs_embedding_idx
        WHERE tenant_id = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (probe_embedding_text, tenant_id, probe_embedding_text, k),
    ).fetchall()
    return [(r[0], r[1], r[2], r[3], r[4], r[5], float(r[6])) for r in rows if r[6] is not None]


def _knn_hits(
    conn: psycopg.Connection,
    probe_embedding_text: str,
    *,
    top_k: int,
    max_k: int,
    threshold: float,
    tenant_id: UUID,
) -> tuple[list[tuple[UUID, str, datetime, UUID | None, UUID, str, float]], bool]:
    """Adaptive K: post-LIMIT filtering must not cap recall. If the farthest
    returned neighbor still clears the threshold, there may be more beyond it —
    double K and retry, bounded by max_k. Returns (hits, truncated): truncated
    means the boundary was still hot at max_k (design review 2026-07-03)."""
    k = top_k
    while True:
        hits = _knn_query(conn, probe_embedding_text, k, tenant_id)
        exhausted = len(hits) < k
        boundary_hot = bool(hits) and (1.0 - hits[-1][6]) >= threshold
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
    tenant_id: UUID = DEFAULT_TENANT_ID,
) -> Closure:
    # Late-bound so tests can patch the module attributes.
    threshold = default_threshold() if threshold is None else threshold
    top_k = KNN_TOP_K if top_k is None else top_k
    max_k = KNN_MAX_K if max_k is None else max_k
    max_rounds = MAX_ROUNDS if max_rounds is None else max_rounds

    seed_rows = conn.execute(
        "SELECT belief_id, created_at FROM beliefs WHERE tenant_id = %s AND source_id = %s",
        (tenant_id, source_id),
    ).fetchall()
    seed_ids = [r[0] for r in seed_rows]

    # Window anchor: when the source ENTERED the system, not its first recorded
    # citation — an unrecorded paraphrase can predate the first explicit seed
    # (design review 2026-07-03). LEAST with the seed minimum for safety.
    src_row = conn.execute(
        "SELECT created_at FROM sources WHERE tenant_id = %s AND source_id = %s",
        (tenant_id, source_id),
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

        explicit = _explicit_descendants(conn, frontier, tenant_id) - closure if frontier else set()
        closure |= explicit
        to_probe = [b for b in (set(frontier) | explicit) if b not in probed]
        probed |= set(to_probe)

        implicit: set[UUID] = set()
        if to_probe:
            emb_rows = conn.execute(
                "SELECT belief_id, embedding::text, content FROM beliefs"
                " WHERE tenant_id = %s AND belief_id = ANY(%s) AND embedding IS NOT NULL",
                (tenant_id, to_probe),
            ).fetchall()
            t0 = time.perf_counter()
            # Best-parent-wins per hit within the round: when several probes match
            # the same new belief, record the single edge to the HIGHEST-similarity
            # probe, not whichever the (unordered) scan returned first (review
            # 2026-07-03). Buffer, then commit the winners to the closure.
            best: dict[UUID, tuple[UUID, float, str, str | None, str]] = {}
            for probe_id, emb_text, probe_content in emb_rows:
                hits, truncated = _knn_hits(
                    conn,
                    emb_text,
                    top_k=top_k,
                    max_k=max_k,
                    threshold=threshold,
                    tenant_id=tenant_id,
                )
                if truncated:
                    knn_truncated = True
                for (
                    hit_id,
                    status,
                    created_at,
                    hit_source_id,
                    hit_tenant_id,
                    hit_content,
                    dist,
                ) in hits:
                    similarity = 1.0 - dist
                    relation = None
                    if hit_source_id is not None:
                        relation = conn.execute(
                            "SELECT relation, evidence_method, evidence_model, evidence_version"
                            " FROM semantic_relations WHERE tenant_id = %s"
                            " AND ((left_belief_id = %s AND right_belief_id = %s"
                            "       AND relation IN ('equivalent', 'entails'))"
                            " OR (left_belief_id = %s AND right_belief_id = %s"
                            "       AND relation = 'equivalent'))"
                            " ORDER BY confidence DESC LIMIT 1",
                            (tenant_id, probe_id, hit_id, hit_id, probe_id),
                        ).fetchone()
                        if relation is None and " ".join(probe_content.lower().split()) == " ".join(
                            hit_content.lower().split()
                        ):
                            relation = ("equivalent", "exact_content", None, "v1")
                    if (
                        hit_id == probe_id
                        or hit_id in closure
                        or hit_tenant_id != tenant_id
                        or similarity < threshold
                        or status not in _TAINTABLE
                        # Vector inference finds unattributed copies. A belief
                        # with its own recorded source has independent
                        # provenance and must not be overridden by topical
                        # similarity alone (for example, a trusted 30-day
                        # policy beside a poisoned 365-day claim).
                        or (hit_source_id is not None and relation is None)
                        or (window_start is not None and created_at < window_start)
                    ):
                        continue
                    evidence_method = relation[1] if relation is not None else "vector_similarity"
                    evidence_model = relation[2] if relation is not None else None
                    evidence_version = relation[3] if relation is not None else "v1"
                    current = best.get(hit_id)
                    if current is None or similarity > current[1]:
                        best[hit_id] = (
                            probe_id,
                            similarity,
                            evidence_method,
                            evidence_model,
                            evidence_version,
                        )
            knn_ms += (time.perf_counter() - t0) * 1000
            for hit_id in sorted(best, key=str):
                parent_id, similarity, method, model, version = best[hit_id]
                implicit.add(hit_id)
                closure.add(hit_id)
                inferred_edges.append(
                    InferredEdge(
                        child_id=hit_id,
                        parent_id=parent_id,
                        score=round(similarity, 4),
                        evidence_method=method,
                        evidence_model=model,
                        evidence_version=version,
                    )
                )

        frontier = sorted(explicit | implicit, key=str)

    member_ids = sorted(closure, key=str)
    agent_ids: list[UUID] = []
    if member_ids:
        agent_ids = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT agent_id FROM beliefs"
                " WHERE tenant_id = %s AND belief_id = ANY(%s)",
                (tenant_id, member_ids),
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

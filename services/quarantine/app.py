"""quarantine-service: executes recant(source_id) (spec section 5).

One serializable transaction: compute the closure (explicit CTE + vector kNN,
via the taint engine on this same connection), materialize inferred edges, flip
the closure to quarantined, open the incident, write the attested quarantine
action, and emit the outbox event the W3 changefeed fanout consumes. Retried as
a whole on SQLSTATE 40001 by run_txn.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from services.common.auth import Principal, auth_required, require_roles
from services.common.config import cors_origins
from services.common.db import run_tenant_txn, run_txn
from services.common.idempotency import replay, request_hash, store, validate_key
from services.common.logging import bind_incident, configure
from services.quarantine.action import action_digest, canonical_action_payload
from services.quarantine.models import (
    InferredEdgeOut,
    PreviewIn,
    PreviewOut,
    RecantIn,
    RecantOut,
)
from services.taint_engine.engine import Closure, compute_closure

try:
    from services.attest_gateway.signer import quarantine_signer_for
except ImportError:  # pragma: no cover
    raise

log = configure("quarantine")

app = FastAPI(title="recant quarantine-service")

# The console reads the judge-overlay chips from this header; without the CORS
# expose rule a browser fetch cannot see it (design review 2026-07-03). Values
# never contain commas, so a fetch-joined multi-value splits cleanly on ','.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Recant-Primitive"],
)

# Test-only seam: called inside the recant transaction after the flip and outbox
# writes, before commit. The atomicity test parks the transaction here while a
# concurrent reader proves the flip is invisible until commit. Never set outside
# tests.
_after_flip_hook: Callable[[], None] | None = None


@dataclass
class _RecantResult:
    closure: Closure
    incident_id: UUID
    created_at: datetime
    newly_flipped: list[tuple[UUID, UUID]]  # (belief_id, agent_id)


def _require_source(conn: psycopg.Connection, source_id: UUID, tenant_id: UUID) -> None:
    if (
        conn.execute(
            "SELECT 1 FROM sources WHERE tenant_id = %s AND source_id = %s",
            (tenant_id, source_id),
        ).fetchone()
        is None
    ):
        raise HTTPException(status_code=404, detail="unknown source")


def _closure_out_fields(closure: Closure) -> dict:
    return {
        "source_id": closure.source_id,
        "closure_ids": closure.member_ids,
        "agent_ids": closure.agent_ids,
        "inferred_edges": [
            InferredEdgeOut(
                child_id=e.child_id,
                parent_id=e.parent_id,
                score=e.score,
                evidence_method=e.evidence_method,
                evidence_model=e.evidence_model,
                evidence_version=e.evidence_version,
            )
            for e in closure.inferred_edges
        ],
        "rounds": closure.rounds,
        "threshold": closure.threshold,
        "rounds_capped": closure.rounds_capped,
        "knn_truncated": closure.knn_truncated,
    }


@app.get("/healthz")
def healthz():
    try:
        run_txn(lambda conn: conn.execute("SELECT 1").fetchone())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unreachable") from exc
    return {"status": "ok"}


@app.post("/taint/preview", response_model=PreviewOut)
def preview(
    body: PreviewIn,
    response: Response,
    principal: Principal = Depends(require_roles("writer", "operator", "auditor")),
) -> PreviewOut:
    def txn(conn: psycopg.Connection) -> tuple[Closure, int]:
        _require_source(conn, body.source_id, principal.tenant_id)
        closure = compute_closure(conn, body.source_id, tenant_id=principal.tenant_id)
        would_flip = 0
        if closure.member_ids:
            count_row = conn.execute(
                "SELECT count(*) FROM beliefs WHERE tenant_id = %s AND belief_id = ANY(%s)"
                " AND status IN ('active','suspect')",
                (principal.tenant_id, closure.member_ids),
            ).fetchone()
            assert count_row is not None
            would_flip = count_row[0]
        return closure, int(would_flip)

    closure, would_flip = run_tenant_txn(principal.tenant_id, txn)
    response.headers.append("X-Recant-Primitive", f"VECTOR kNN | {closure.knn_ms}ms")
    return PreviewOut(**_closure_out_fields(closure), would_flip=would_flip)


@app.post("/recant", response_model=RecantOut)
def recant(
    body: RecantIn,
    response: Response,
    principal: Principal = Depends(require_roles("operator")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RecantOut:
    t0 = time.perf_counter()
    actor = principal.subject if auth_required() else body.actor
    key = validate_key(idempotency_key)
    request_digest = request_hash({"source_id": body.source_id, "actor": actor})
    try:
        signer = quarantine_signer_for(actor)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def txn(conn: psycopg.Connection) -> _RecantResult | RecantOut:
        prior = replay(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/recant",
            key=key,
            digest=request_digest,
        )
        if prior is not None:
            return RecantOut.model_validate(prior)
        _require_source(conn, body.source_id, principal.tenant_id)
        closure = compute_closure(conn, body.source_id, tenant_id=principal.tenant_id)

        for e in closure.inferred_edges:
            conn.execute(
                "INSERT INTO derivations"
                " (tenant_id, child_id, parent_id, kind, score, evidence_method,"
                " evidence_model, evidence_version)"
                " VALUES (%s, %s, %s, 'inferred', %s, %s, %s, %s)"
                " ON CONFLICT (child_id, parent_id) DO NOTHING",
                (
                    principal.tenant_id,
                    e.child_id,
                    e.parent_id,
                    e.score,
                    e.evidence_method,
                    e.evidence_model,
                    e.evidence_version,
                ),
            )

        newly_flipped: list[tuple[UUID, UUID]] = []
        if closure.member_ids:
            newly_flipped = conn.execute(
                "UPDATE beliefs SET status = 'quarantined'"
                " WHERE tenant_id = %s AND belief_id = ANY(%s)"
                " AND status IN ('active','suspect')"
                " RETURNING belief_id, agent_id",
                (principal.tenant_id, closure.member_ids),
            ).fetchall()

        incident_row = conn.execute(
            "INSERT INTO incidents (tenant_id, source_id, opened_by) VALUES (%s, %s, %s)"
            " RETURNING incident_id, created_at",
            (principal.tenant_id, body.source_id, actor),
        ).fetchone()
        assert incident_row is not None
        incident_id, created_at = incident_row

        flipped_ids = [b for b, _ in newly_flipped]
        payload = canonical_action_payload(
            incident_id=incident_id,
            source_id=body.source_id,
            newly_flipped_ids=flipped_ids,
            belief_count=len(flipped_ids),
            actor=actor,
            ts=created_at,
            tenant_id=principal.tenant_id,
            attestation_version="v2",
        )
        sig = signer.sign(action_digest(payload))
        conn.execute(
            "INSERT INTO quarantine_actions"
            " (tenant_id, incident_id, belief_count, actor, sig, newly_flipped_ids,"
            " signer_pubkey, signing_algorithm, signer_key_id, attestation_version)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'v2')",
            (
                principal.tenant_id,
                incident_id,
                len(flipped_ids),
                actor,
                sig,
                flipped_ids,
                signer.public_key_bytes(),
                signer.algorithm,
                signer.key_id,
            ),
        )

        # Permits are execution capabilities, so revoke them in the same commit
        # as the quarantine rather than waiting for asynchronous fanout. The
        # existing worker still aborts agent_actions and evicts runtime memory.
        if closure.member_ids:
            conn.execute(
                "UPDATE action_permits AS p SET revoked_at = now(),"
                " revoke_reason = 'recant', incident_id = %s"
                " FROM action_decisions AS d"
                " WHERE p.tenant_id = %s AND d.tenant_id = p.tenant_id"
                " AND d.decision_id = p.decision_id AND p.consumed_at IS NULL"
                " AND p.revoked_at IS NULL AND d.support_belief_ids && %s",
                (incident_id, principal.tenant_id, closure.member_ids),
            )

        # Eviction contract (design review 2026-07-03): the W3 fanout keys on
        # `evictions`, grouped per agent from the flip's RETURNING pairs — only
        # newly flipped beliefs evict, so a repeat recant does not re-evict.
        evictions: dict[UUID, list[UUID]] = defaultdict(list)
        for belief_id, agent_id in newly_flipped:
            evictions[agent_id].append(belief_id)
        conn.execute(
            "INSERT INTO memory_events (tenant_id, kind, incident_id, payload)"
            " VALUES (%s, 'recant', %s, %s)",
            (
                principal.tenant_id,
                incident_id,
                json.dumps(
                    {
                        "source_id": str(body.source_id),
                        "tenant_id": str(principal.tenant_id),
                        "actor": actor,
                        "closure_ids": [str(b) for b in closure.member_ids],
                        "evictions": [
                            {"agent_id": str(a), "belief_ids": sorted(str(b) for b in bs)}
                            for a, bs in sorted(evictions.items(), key=lambda kv: str(kv[0]))
                        ],
                        "inferred_edges": [
                            {
                                "child_id": str(e.child_id),
                                "parent_id": str(e.parent_id),
                                "score": e.score,
                                "evidence_method": e.evidence_method,
                            }
                            for e in closure.inferred_edges
                        ],
                    }
                ),
            ),
        )
        if _after_flip_hook is not None:
            _after_flip_hook()
        raw_result = RecantOut(
            **_closure_out_fields(closure),
            incident_id=incident_id,
            belief_count=len(newly_flipped),
            newly_flipped_ids=[belief_id for belief_id, _ in newly_flipped],
        )
        store(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/recant",
            key=key,
            digest=request_digest,
            response_status=200,
            response_body=raw_result.model_dump(mode="json"),
        )
        return _RecantResult(closure, incident_id, created_at, newly_flipped)

    result = run_tenant_txn(principal.tenant_id, txn)
    if isinstance(result, RecantOut):
        response.headers.append("X-Recant-Primitive", "SERIALIZABLE TXN | replay")
        return result
    txn_ms = int((time.perf_counter() - t0) * 1000)

    with bind_incident(str(result.incident_id)):
        log.info(
            "recant complete",
            extra={
                "fields": {
                    "source_id": str(body.source_id),
                    "actor": actor,
                    "closure_size": len(result.closure.member_ids),
                    "belief_count": len(result.newly_flipped),
                    "inferred_edges": len(result.closure.inferred_edges),
                    "rounds": result.closure.rounds,
                    "rounds_capped": result.closure.rounds_capped,
                    "knn_truncated": result.closure.knn_truncated,
                    "knn_ms": result.closure.knn_ms,
                    "txn_ms": txn_ms,
                }
            },
        )
        if result.closure.rounds_capped:
            log.warning("closure hit the round cap; result may be incomplete (tune MAX_ROUNDS)")
        if result.closure.knn_truncated:
            log.warning(
                "kNN boundary still hot at max_k; result may be incomplete"
                " (tune RECANT_TAINT_MAX_K)"
            )

    response.headers.append("X-Recant-Primitive", f"SERIALIZABLE TXN | {txn_ms}ms")
    response.headers.append("X-Recant-Primitive", f"VECTOR kNN | {result.closure.knn_ms}ms")
    return RecantOut(
        **_closure_out_fields(result.closure),
        incident_id=result.incident_id,
        belief_count=len(result.newly_flipped),
        newly_flipped_ids=[b for b, _ in result.newly_flipped],
    )

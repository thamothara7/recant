"""forensics-api: read-only queries for custody inspection and time travel (spec section 5).

Provides AS OF SYSTEM TIME queries (proof moment 5), custody-chain reads,
incident summaries, and text-template incident affidavits. All endpoints
are read-only. The Bedrock Claude integration for AI-generated affidavits
arrives with U3 (AWS credentials).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg import sql

from services.attest_gateway import chain
from services.attest_gateway.signer import (
    control_signer_for,
    quarantine_signer_for,
    signer_for_agent,
    verify_signature,
)
from services.common.attestation import sha256
from services.common.auth import Principal, require_roles
from services.common.config import cors_origins
from services.common.db import (
    get_pool,
    run_tenant_txn,
    run_txn,
    tenant_role_name,
    tenant_roles_enabled,
)
from services.common.logging import bind_incident, configure
from services.forensics.affidavit import (
    generate_affidavit,
    generate_affidavit_text,  # noqa: F401  (re-export; unit tests import from here)
)
from services.forensics.archive import MissingBucket, S3EvidenceArchiver
from services.forensics.checkpoint import (
    MissingCheckpointBucket,
    S3CheckpointPublisher,
    checkpoint_payload,
    custody_leaves,
    merkle_root,
    published_document,
)
from services.forensics.models import (
    ActionOut,
    AffidavitOut,
    ArchiveOut,
    BeliefSnapshot,
    BeliefsPage,
    BoardAgent,
    BoardOut,
    BoardSource,
    CheckpointOut,
    CheckpointVerificationOut,
    CustodyChainOut,
    CustodyStep,
    DerivationOut,
    EventOut,
    IncidentSummary,
    ProvenanceOut,
)
from services.quarantine.action import action_digest, canonical_action_payload

log = configure("forensics")

app = FastAPI(title="recant forensics-api")

# The console reads judge-overlay chips from this header cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Recant-Primitive"],
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_read_txn(fn, *, tenant_id: UUID, as_of: datetime | None = None):
    """Run fn in a read-only transaction, optionally at a past timestamp.

    AS OF SYSTEM TIME queries never conflict and do not need retry.
    CockroachDB rejects a bind placeholder after AS OF SYSTEM TIME
    ("type with ID 0 does not exist"), so the timestamp is inlined as a
    quoted literal. Safe: FastAPI has already parsed ``as_of`` into a
    datetime, and sql.Literal escapes the rendered string.
    """
    with get_pool().connection() as conn:
        with conn.transaction():
            if as_of:
                conn.execute(
                    sql.SQL("SET TRANSACTION AS OF SYSTEM TIME {}").format(
                        sql.Literal(as_of.isoformat())
                    )
                )
            if tenant_roles_enabled():
                conn.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(tenant_role_name(tenant_id)))
                )
            return fn(conn)


_BELIEF_COLS = (
    "b.belief_id, b.agent_id, b.seq, b.content, b.status::text, b.created_at,"
    " b.hash, b.prev_hash, b.sig, b.source_id, b.authority_rank, b.origin_source_ids,"
    " b.context_receipt_id, b.provenance_method, b.provenance_version,"
    " b.attestation_version"
)


def _belief_snapshot(row) -> BeliefSnapshot:
    return BeliefSnapshot(
        belief_id=row[0],
        agent_id=row[1],
        seq=row[2],
        content=row[3],
        status=row[4],
        created_at=row[5],
        hash=bytes(row[6]).hex(),
        prev_hash=bytes(row[7]).hex() if row[7] else "",
        sig=bytes(row[8]).hex(),
        source_id=row[9],
        authority_rank=int(row[10]),
        origin_source_ids=list(row[11] or []),
        context_receipt_id=row[12],
        provenance_method=row[13],
        provenance_version=row[14],
        attestation_version=row[15],
    )


def _require_agent(conn: psycopg.Connection, agent_id: UUID, tenant_id: UUID):
    row = conn.execute(
        "SELECT name, pubkey, head_hash, head_seq, signing_algorithm, kms_key_arn"
        " FROM agents WHERE tenant_id = %s AND agent_id = %s",
        (tenant_id, agent_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    return row


def _derivations_for(
    conn: psycopg.Connection, belief_id: UUID, tenant_id: UUID
) -> tuple[list[DerivationOut], list[DerivationOut]]:
    """Return (parents, children) derivation edges for a belief."""
    rows = conn.execute(
        "SELECT child_id, parent_id, kind, score, evidence_method, evidence_model,"
        " evidence_version FROM derivations"
        " WHERE tenant_id = %s AND (child_id = %s OR parent_id = %s)",
        (tenant_id, belief_id, belief_id),
    ).fetchall()
    parents = [
        DerivationOut(
            child_id=r[0],
            parent_id=r[1],
            kind=r[2],
            score=r[3],
            evidence_method=r[4],
            evidence_model=r[5],
            evidence_version=r[6],
        )
        for r in rows
        if r[0] == belief_id
    ]
    children = [
        DerivationOut(
            child_id=r[0],
            parent_id=r[1],
            kind=r[2],
            score=r[3],
            evidence_method=r[4],
            evidence_model=r[5],
            evidence_version=r[6],
        )
        for r in rows
        if r[1] == belief_id
    ]
    return parents, children


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz():
    try:
        run_txn(lambda conn: conn.execute("SELECT 1").fetchone())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unreachable") from exc
    return {"status": "ok"}


@app.get("/board", response_model=BoardOut)
def board(
    response: Response,
    principal: Principal = Depends(require_roles("writer", "auditor")),
):
    """The whole provenance graph in one read, for the console board.

    Read-only. One serializable transaction so the beliefs and the edges that
    connect them are a consistent snapshot (no belief referencing a derivation
    to a row a concurrent writer has not committed).
    """
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        agents = conn.execute(
            "SELECT agent_id, name, region, pubkey, signing_algorithm"
            " FROM agents WHERE tenant_id = %s ORDER BY name",
            (principal.tenant_id,),
        ).fetchall()
        sources = conn.execute(
            "SELECT source_id, kind, uri, trust_tier, region, authority_rank, issuer_subject"
            " FROM sources WHERE tenant_id = %s ORDER BY created_at",
            (principal.tenant_id,),
        ).fetchall()
        beliefs = conn.execute(
            f"SELECT {_BELIEF_COLS} FROM beliefs b"
            " WHERE b.tenant_id = %s ORDER BY b.agent_id, b.seq",
            (principal.tenant_id,),
        ).fetchall()
        derivations = conn.execute(
            "SELECT child_id, parent_id, kind, score, evidence_method, evidence_model,"
            " evidence_version FROM derivations WHERE tenant_id = %s",
            (principal.tenant_id,),
        ).fetchall()
        return agents, sources, beliefs, derivations

    agents, sources, beliefs, derivations = run_tenant_txn(principal.tenant_id, txn)
    ms = int((time.perf_counter() - t0) * 1000)
    response.headers.append("X-Recant-Primitive", f"SERIALIZABLE TXN | {ms}ms")

    return BoardOut(
        agents=[
            BoardAgent(
                agent_id=r[0],
                name=r[1],
                region=r[2],
                pubkey8=bytes(r[3]).hex()[:8],
                signing_algorithm=r[4],
            )
            for r in agents
        ],
        sources=[
            BoardSource(
                source_id=r[0],
                kind=r[1],
                uri=r[2],
                trust_tier=r[3],
                region=r[4],
                authority_rank=int(r[5]),
                issuer=r[6],
            )
            for r in sources
        ],
        beliefs=[_belief_snapshot(r) for r in beliefs],
        derivations=[
            DerivationOut(
                child_id=r[0],
                parent_id=r[1],
                kind=r[2],
                score=r[3],
                evidence_method=r[4],
                evidence_model=r[5],
                evidence_version=r[6],
            )
            for r in derivations
        ],
    )


@app.get("/agents/{agent_id}/beliefs", response_model=BeliefsPage)
def agent_beliefs(
    agent_id: UUID,
    response: Response,
    as_of: datetime | None = None,
    principal: Principal = Depends(require_roles("writer", "auditor")),
):
    """Belief set for an agent, optionally at a past timestamp (AOST).

    This is Proof Moment 5: side-by-side "what agent B believed at 14:32 vs now".
    When ``as_of`` is provided, the query runs inside a read-only transaction with
    ``SET TRANSACTION AS OF SYSTEM TIME``, CockroachDB's time-travel primitive.
    FastAPI parses ``as_of`` as a datetime, so garbage input gets a 422 before
    any SQL runs.
    """
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        agent_row = _require_agent(conn, agent_id, principal.tenant_id)
        agent_name = agent_row[0]
        rows = conn.execute(
            f"SELECT {_BELIEF_COLS} FROM beliefs b"
            " WHERE b.tenant_id = %s AND b.agent_id = %s ORDER BY b.seq",
            (principal.tenant_id, agent_id),
        ).fetchall()
        return agent_name, rows

    agent_name, rows = _run_read_txn(txn, tenant_id=principal.tenant_id, as_of=as_of)
    beliefs = [_belief_snapshot(r) for r in rows]
    as_of_str = as_of.isoformat() if as_of else None

    if as_of:
        ms = int((time.perf_counter() - t0) * 1000)
        response.headers.append("X-Recant-Primitive", f"AOST @ {as_of_str} | {ms}ms")
        log.info(
            "aost query",
            extra={
                "fields": {
                    "agent_id": str(agent_id),
                    "as_of": as_of_str,
                    "count": len(beliefs),
                    "ms": ms,
                }
            },
        )

    return BeliefsPage(
        agent_id=agent_id,
        agent_name=agent_name,
        as_of=as_of_str,
        beliefs=beliefs,
        count=len(beliefs),
    )


@app.get("/agents/{agent_id}/custody-chain", response_model=CustodyChainOut)
def custody_chain(
    agent_id: UUID,
    response: Response,
    principal: Principal = Depends(require_roles("writer", "auditor")),
):
    """Full custody chain with derivation edges and chain verification."""
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        agent_row = _require_agent(conn, agent_id, principal.tenant_id)
        agent_name, pubkey, head_hash, head_seq, signing_algorithm, kms_key_arn = agent_row

        rows = conn.execute(
            f"SELECT {_BELIEF_COLS} FROM beliefs b"
            " WHERE b.tenant_id = %s AND b.agent_id = %s ORDER BY b.seq",
            (principal.tenant_id, agent_id),
        ).fetchall()

        steps: list[CustodyStep] = []
        for r in rows:
            belief = _belief_snapshot(r)
            parents, children = _derivations_for(conn, r[0], principal.tenant_id)
            steps.append(CustodyStep(belief=belief, parents=parents, children=children))

        # Verify the hash chain
        records = [
            chain.ChainRecord(
                agent_id=agent_id,
                seq=r[2],
                content=r[3],
                source_id=r[9],
                parent_ids=[d.parent_id for d in steps[i].parents if d.kind == "explicit"],
                ts=r[5],
                prev_hash=bytes(r[7]),
                hash=bytes(r[6]),
                tenant_id=principal.tenant_id,
                context_receipt_id=r[12],
                authority_rank=int(r[10]),
                origin_source_ids=list(r[11] or []),
                provenance_method=r[13],
                provenance_version=r[14],
                attestation_version=r[15],
            )
            for i, r in enumerate(rows)
        ]
        valid, _ = chain.verify_chain(records)

        # A valid prefix is not necessarily the full chain. The agent row is
        # the committed head, so compare it before reporting custody as valid.
        if valid:
            if records:
                valid = (
                    records[-1].seq == int(head_seq)
                    and head_hash is not None
                    and records[-1].hash == bytes(head_hash)
                )
            else:
                valid = int(head_seq) == 0 and head_hash is None

        # Also verify signatures
        if valid and records:
            pubkey_bytes = bytes(pubkey)
            try:
                trusted_signer = signer_for_agent(agent_name, kms_key_arn)
                valid = (
                    signing_algorithm == trusted_signer.algorithm
                    and pubkey_bytes == trusted_signer.public_key_bytes()
                )
            except (RuntimeError, ValueError):
                valid = False
            for record, r in zip(records, rows, strict=True):
                if not valid or not verify_signature(
                    pubkey_bytes, record.hash, bytes(r[8]), signing_algorithm
                ):
                    valid = False
                    break

        return agent_name, steps, valid

    agent_name, steps, valid = run_tenant_txn(principal.tenant_id, txn)
    ms = int((time.perf_counter() - t0) * 1000)
    response.headers.append("X-Recant-Primitive", f"SERIALIZABLE TXN | {ms}ms")

    return CustodyChainOut(
        agent_id=agent_id,
        agent_name=agent_name,
        chain_length=len(steps),
        steps=steps,
        valid=valid,
    )


@app.get("/incidents/{incident_id}", response_model=IncidentSummary)
def incident_summary(
    incident_id: UUID,
    response: Response,
    principal: Principal = Depends(require_roles("writer", "auditor")),
):
    """Incident summary with source, closure, actions, and event timeline."""
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        # Incident + source
        row = conn.execute(
            "SELECT i.incident_id, i.source_id, i.opened_by, i.created_at,"
            " s.kind, s.uri, s.trust_tier"
            " FROM incidents i JOIN sources s"
            " ON i.source_id = s.source_id AND i.tenant_id = s.tenant_id"
            " WHERE i.tenant_id = %s AND i.incident_id = %s",
            (principal.tenant_id, incident_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown incident")
        inc_id, source_id, opened_by, created_at, s_kind, s_uri, s_tier = row

        # Quarantine actions
        action_rows = conn.execute(
            "SELECT action_id, belief_count, actor, sig, newly_flipped_ids, created_at,"
            " signer_pubkey, signing_algorithm, signer_key_id, attestation_version"
            " FROM quarantine_actions WHERE tenant_id = %s AND incident_id = %s"
            " ORDER BY created_at",
            (principal.tenant_id, incident_id),
        ).fetchall()

        actions: list[ActionOut] = []
        all_flipped: list[UUID] = []
        for ar in action_rows:
            (
                a_id,
                a_count,
                actor,
                sig,
                flipped,
                a_ts,
                stored_pubkey,
                stored_algorithm,
                stored_key_id,
                attestation_version,
            ) = ar
            sig_bytes = bytes(sig)
            flipped_ids = list(flipped) if flipped else []
            all_flipped.extend(flipped_ids)

            # Verify the action signature from stored rows alone (decision 14)
            try:
                payload = canonical_action_payload(
                    incident_id=incident_id,
                    source_id=source_id,
                    newly_flipped_ids=flipped_ids,
                    belief_count=a_count,
                    actor=actor,
                    ts=a_ts,
                    tenant_id=principal.tenant_id,
                    attestation_version=attestation_version,
                )
                trusted_signer = quarantine_signer_for(actor)
                expected_pub = trusted_signer.public_key_bytes()
                sig_valid = (
                    stored_pubkey is not None
                    and bytes(stored_pubkey) == expected_pub
                    and stored_algorithm == trusted_signer.algorithm
                    and stored_key_id == trusted_signer.key_id
                    and verify_signature(
                        expected_pub,
                        action_digest(payload),
                        sig_bytes,
                        trusted_signer.algorithm,
                    )
                )
            except Exception:
                sig_valid = False

            actions.append(
                ActionOut(
                    action_id=a_id,
                    belief_count=a_count,
                    actor=actor,
                    sig=sig_bytes.hex(),
                    newly_flipped_ids=flipped_ids,
                    created_at=a_ts,
                    sig_valid=sig_valid,
                    signing_algorithm=stored_algorithm or "ed25519",
                    signer_key_id=stored_key_id or "legacy",
                    attestation_version=attestation_version,
                )
            )

        # Per-agent affected counts
        agents_affected: list[dict] = []
        if all_flipped:
            agent_rows = conn.execute(
                "SELECT a.agent_id, a.name, count(*) FROM beliefs b"
                " JOIN agents a ON b.agent_id = a.agent_id"
                " WHERE b.tenant_id = %s AND a.tenant_id = %s"
                " AND b.belief_id = ANY(%s) GROUP BY a.agent_id, a.name",
                (principal.tenant_id, principal.tenant_id, all_flipped),
            ).fetchall()
            agents_affected = [
                {"agent_id": str(r[0]), "agent_name": r[1], "belief_count": r[2]}
                for r in agent_rows
            ]

        # Events timeline
        event_rows = conn.execute(
            "SELECT event_id, kind, created_at, payload FROM memory_events"
            " WHERE tenant_id = %s AND incident_id = %s ORDER BY created_at",
            (principal.tenant_id, incident_id),
        ).fetchall()
        events = [
            EventOut(
                event_id=r[0],
                kind=r[1],
                created_at=r[2],
                payload=json.loads(r[3]) if isinstance(r[3], str) else r[3],
            )
            for r in event_rows
        ]

        return IncidentSummary(
            incident_id=inc_id,
            source_id=source_id,
            source_uri=s_uri,
            source_kind=s_kind,
            source_trust_tier=s_tier,
            opened_by=opened_by,
            created_at=created_at,
            closure_size=len(all_flipped),
            agents_affected=agents_affected,
            actions=actions,
            events=events,
        )

    result = run_tenant_txn(principal.tenant_id, txn)
    ms = int((time.perf_counter() - t0) * 1000)
    response.headers.append("X-Recant-Primitive", f"SERIALIZABLE TXN | {ms}ms")
    with bind_incident(str(incident_id)):
        log.info(
            "incident summary",
            extra={"fields": {"closure_size": result.closure_size, "ms": ms}},
        )
    return result


def _checkpoint_out(row) -> CheckpointOut:
    return CheckpointOut(
        checkpoint_id=row[0],
        root_hash=bytes(row[1]).hex(),
        leaf_count=int(row[2]),
        previous_root_hash=bytes(row[3]).hex() if row[3] is not None else None,
        external_uri=row[4],
        created_at=row[5],
        sig=bytes(row[6]).hex(),
        signing_algorithm=row[7],
        signer_key_id=row[8],
    )


_CHECKPOINT_SELECT = (
    "SELECT checkpoint_id, root_hash, leaf_count, previous_root_hash, external_uri,"
    " created_at, sig, signing_algorithm, signer_key_id FROM custody_checkpoints"
)


@app.post("/checkpoints", response_model=CheckpointOut, status_code=201)
def create_checkpoint(
    principal: Principal = Depends(require_roles("operator")),
) -> CheckpointOut:
    if os.environ.get("RECANT_ENV", "").strip().lower() == "production" and not os.environ.get(
        "RECANT_CHECKPOINT_BUCKET"
    ):
        raise HTTPException(
            status_code=503,
            detail="RECANT_CHECKPOINT_BUCKET is required for production checkpoints",
        )
    try:
        signer = control_signer_for("checkpoint")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    checkpoint_id = uuid4()

    def txn(conn):
        # Serialize checkpoint creation per tenant, including the empty-history
        # case where locking the previous checkpoint row would lock nothing.
        tenant_row = conn.execute(
            "SELECT tenant_id FROM tenants WHERE tenant_id = %s FOR UPDATE",
            (principal.tenant_id,),
        ).fetchone()
        if tenant_row is None:
            raise HTTPException(status_code=404, detail="unknown tenant")
        head_rows = conn.execute(
            "SELECT agent_id, head_seq, head_hash FROM agents"
            " WHERE tenant_id = %s ORDER BY agent_id",
            (principal.tenant_id,),
        ).fetchall()
        leaves = custody_leaves(head_rows)
        root = merkle_root(leaves)
        previous = conn.execute(
            "SELECT root_hash FROM custody_checkpoints WHERE tenant_id = %s"
            " ORDER BY created_at DESC LIMIT 1",
            (principal.tenant_id,),
        ).fetchone()
        previous_root = bytes(previous[0]) if previous else None
        created_row = conn.execute("SELECT now()").fetchone()
        assert created_row is not None
        created_at = created_row[0]
        payload = checkpoint_payload(
            checkpoint_id=checkpoint_id,
            tenant_id=principal.tenant_id,
            root_hash=root,
            leaves=leaves,
            previous_root_hash=previous_root,
            created_at=created_at,
        )
        sig = signer.sign(sha256(payload))
        conn.execute(
            "INSERT INTO custody_checkpoints"
            " (checkpoint_id, tenant_id, root_hash, leaf_count, leaves, previous_root_hash,"
            " sig, signer_pubkey, signing_algorithm, signer_key_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                checkpoint_id,
                principal.tenant_id,
                root,
                len(leaves),
                json.dumps(leaves),
                previous_root,
                sig,
                signer.public_key_bytes(),
                signer.algorithm,
                signer.key_id,
                created_at,
            ),
        )
        document = published_document(
            payload=payload,
            sig=sig,
            pubkey=signer.public_key_bytes(),
            algorithm=signer.algorithm,
            key_id=signer.key_id,
        )
        return root, previous_root, created_at, sig, document

    root, previous_root, created_at, sig, document = run_tenant_txn(principal.tenant_id, txn)
    external_uri = None
    if os.environ.get("RECANT_CHECKPOINT_BUCKET"):
        try:
            external_uri = S3CheckpointPublisher().publish(
                principal.tenant_id, checkpoint_id, document
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"checkpoint was stored locally but external publication failed: {exc}",
            ) from exc
        run_tenant_txn(
            principal.tenant_id,
            lambda conn: conn.execute(
                "UPDATE custody_checkpoints SET external_uri = %s"
                " WHERE tenant_id = %s AND checkpoint_id = %s",
                (external_uri, principal.tenant_id, checkpoint_id),
            ),
        )
    return CheckpointOut(
        checkpoint_id=checkpoint_id,
        root_hash=root.hex(),
        leaf_count=json.loads(document)["payload"]["leaf_count"],
        previous_root_hash=previous_root.hex() if previous_root else None,
        external_uri=external_uri,
        created_at=created_at,
        sig=sig.hex(),
        signing_algorithm=signer.algorithm,
        signer_key_id=signer.key_id,
    )


@app.get("/checkpoints/latest", response_model=CheckpointOut)
def latest_checkpoint(
    principal: Principal = Depends(require_roles("auditor", "operator")),
) -> CheckpointOut:
    row = run_tenant_txn(
        principal.tenant_id,
        lambda conn: conn.execute(
            _CHECKPOINT_SELECT + " WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
            (principal.tenant_id,),
        ).fetchone(),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no checkpoint exists")
    return _checkpoint_out(row)


@app.get("/checkpoints/{checkpoint_id}/verify", response_model=CheckpointVerificationOut)
def verify_checkpoint(
    checkpoint_id: UUID,
    principal: Principal = Depends(require_roles("auditor", "operator")),
) -> CheckpointVerificationOut:
    try:
        trusted_signer = control_signer_for("checkpoint")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def txn(conn):
        row = conn.execute(
            "SELECT root_hash, leaves, previous_root_hash, created_at, sig, signer_pubkey,"
            " signing_algorithm, signer_key_id, external_uri FROM custody_checkpoints"
            " WHERE tenant_id = %s AND checkpoint_id = %s",
            (principal.tenant_id, checkpoint_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown checkpoint")
        current = custody_leaves(
            conn.execute(
                "SELECT agent_id, head_seq, head_hash FROM agents"
                " WHERE tenant_id = %s ORDER BY agent_id",
                (principal.tenant_id,),
            ).fetchall()
        )
        return row, current

    row, current_leaves = run_tenant_txn(principal.tenant_id, txn)
    (
        stored_root,
        leaves_value,
        previous_root,
        created_at,
        sig,
        pubkey,
        algorithm,
        key_id,
        external_uri,
    ) = row
    leaves = json.loads(leaves_value) if isinstance(leaves_value, str) else leaves_value
    stored_root = bytes(stored_root)
    payload = checkpoint_payload(
        checkpoint_id=checkpoint_id,
        tenant_id=principal.tenant_id,
        root_hash=stored_root,
        leaves=leaves,
        previous_root_hash=bytes(previous_root) if previous_root is not None else None,
        created_at=created_at,
    )
    signature_valid = (
        key_id == trusted_signer.key_id
        and algorithm == trusted_signer.algorithm
        and bytes(pubkey) == trusted_signer.public_key_bytes()
        and verify_signature(bytes(pubkey), sha256(payload), bytes(sig), algorithm)
    )
    root_valid = merkle_root(leaves) == stored_root
    current_matches = merkle_root(current_leaves) == stored_root
    external_valid = None
    if external_uri:
        expected = published_document(
            payload=payload,
            sig=bytes(sig),
            pubkey=bytes(pubkey),
            algorithm=algorithm,
            key_id=key_id,
        )
        try:
            external_valid = S3CheckpointPublisher().read(external_uri) == expected
        except (MissingCheckpointBucket, OSError, ValueError):
            external_valid = False
        except Exception:
            external_valid = False
    return CheckpointVerificationOut(
        checkpoint_id=checkpoint_id,
        signature_valid=signature_valid,
        merkle_root_valid=root_valid,
        current_root_matches=current_matches,
        external_copy_valid=external_valid,
    )


def _affidavit_structured(incident_id: UUID, summary: IncidentSummary) -> dict:
    """The structured facts both affidavit generators consume (and the
    archive bundles), assembled once from the incident summary."""
    actions_for_text = [
        {
            "action_id": str(act.action_id),
            "sig": act.sig,
            "sig_status": "valid" if act.sig_valid else "INVALID",
            "belief_count": act.belief_count,
        }
        for act in summary.actions
    ]

    events_for_text = [
        {
            "created_at": evt.created_at,
            "kind": evt.kind,
            "summary": json.dumps(evt.payload.get("evictions", []), default=str)[:80]
            if evt.payload
            else "",
        }
        for evt in summary.events
    ]

    return {
        "incident_id": incident_id,
        "created_at": summary.created_at,
        "opened_by": summary.opened_by,
        "source_id": summary.source_id,
        "source_kind": summary.source_kind,
        "source_uri": summary.source_uri,
        "source_trust_tier": summary.source_trust_tier,
        "belief_count": summary.closure_size,
        "agents_affected": summary.agents_affected,
        "actions": actions_for_text,
        "events": events_for_text,
    }


@app.get("/incidents/{incident_id}/affidavit", response_model=AffidavitOut)
def affidavit(
    incident_id: UUID,
    response: Response,
    principal: Principal = Depends(require_roles("writer", "auditor")),
):
    """Forensic affidavit from the incident records.

    RECANT_AFFIDAVIT selects the generator: the deterministic text template
    (default; offline and used by tests) or Bedrock Claude, which writes the
    affidavit from the same structured facts and falls back to the template
    on any Bedrock failure.
    """
    # Reuse the incident summary logic
    summary = incident_summary(incident_id, response, principal)
    text, generated_by = generate_affidavit(_affidavit_structured(incident_id, summary))
    return AffidavitOut(incident_id=incident_id, generated_by=generated_by, text=text)


@app.post("/incidents/{incident_id}/archive", response_model=ArchiveOut)
def archive(
    incident_id: UUID,
    response: Response,
    principal: Principal = Depends(require_roles("operator", "auditor")),
):
    """Write the incident's evidence bundle to S3 (W4 archive leg).

    The bundle is everything a DB-less verifier needs under one prefix:
    the incident summary (with per-action signature verdicts), the
    affidavit, and the custody chain of every affected agent. The database
    is only read; the side effect is the S3 write.
    """
    summary = incident_summary(incident_id, response, principal)
    text, generated_by = generate_affidavit(_affidavit_structured(incident_id, summary))

    documents: dict[str, tuple[str, str]] = {
        "incident.json": (summary.model_dump_json(indent=2), "application/json"),
        "affidavit.txt": (text, "text/plain; charset=utf-8"),
    }
    for agent in summary.agents_affected:
        chain_out = custody_chain(UUID(agent["agent_id"]), response, principal)
        documents[f"custody/{agent['agent_id']}.json"] = (
            chain_out.model_dump_json(indent=2),
            "application/json",
        )

    archiver = S3EvidenceArchiver()
    try:
        keys = archiver.put_bundle(incident_id, documents)
        bucket = archiver.bucket
    except MissingBucket as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    with bind_incident(str(incident_id)):
        log.info(
            "evidence archived",
            extra={"fields": {"bucket": bucket, "keys": len(keys)}},
        )
    return ArchiveOut(
        incident_id=incident_id,
        bucket=bucket,
        keys=keys,
        affidavit_generated_by=generated_by,
    )


@app.get("/beliefs/{belief_id}/provenance", response_model=ProvenanceOut)
def provenance(
    belief_id: UUID,
    response: Response,
    principal: Principal = Depends(require_roles("writer", "auditor")),
):
    """Single belief provenance: parents, source, chain position, verification."""
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        row = conn.execute(
            f"SELECT {_BELIEF_COLS} FROM beliefs b WHERE b.tenant_id = %s AND b.belief_id = %s",
            (principal.tenant_id, belief_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown belief")

        belief = _belief_snapshot(row)
        agent_id = row[1]

        # Agent name + pubkey
        agent_row = conn.execute(
            "SELECT name, pubkey, signing_algorithm, kms_key_arn FROM agents"
            " WHERE tenant_id = %s AND agent_id = %s",
            (principal.tenant_id, agent_id),
        ).fetchone()
        if agent_row is None:
            raise HTTPException(status_code=404, detail="unknown agent")
        agent_name = agent_row[0]
        pubkey = bytes(agent_row[1])
        signing_algorithm = agent_row[2]
        kms_key_arn = agent_row[3]

        # Source info
        source = None
        if row[9]:  # source_id
            src = conn.execute(
                "SELECT source_id, kind, uri, trust_tier, authority_rank, issuer_subject"
                " FROM sources WHERE tenant_id = %s AND source_id = %s",
                (principal.tenant_id, row[9]),
            ).fetchone()
            if src:
                source = {
                    "source_id": str(src[0]),
                    "kind": src[1],
                    "uri": src[2],
                    "trust_tier": src[3],
                    "authority_rank": int(src[4]),
                    "issuer": src[5],
                }

        # Derivations
        parents, children = _derivations_for(conn, belief_id, principal.tenant_id)

        # Verify the chain hash for this specific belief
        explicit_parent_ids = [d.parent_id for d in parents if d.kind == "explicit"]
        prev_hash = bytes(row[7]) if row[7] else chain.GENESIS
        record = chain.ChainRecord(
            agent_id=agent_id,
            seq=row[2],
            content=row[3],
            source_id=row[9],
            parent_ids=explicit_parent_ids,
            ts=row[5],
            prev_hash=prev_hash,
            hash=bytes(row[6]),
            tenant_id=principal.tenant_id,
            context_receipt_id=row[12],
            authority_rank=int(row[10]),
            origin_source_ids=list(row[11] or []),
            provenance_method=row[13],
            provenance_version=row[14],
            attestation_version=row[15],
        )
        try:
            payload = chain.record_payload(record)
        except ValueError:
            payload = b""
        expected_hash = chain.chain_hash(prev_hash, payload)
        chain_valid = bool(payload) and expected_hash == bytes(row[6])

        # Verify signature
        try:
            trusted_signer = signer_for_agent(agent_name, kms_key_arn)
            sig_valid = (
                signing_algorithm == trusted_signer.algorithm
                and pubkey == trusted_signer.public_key_bytes()
                and verify_signature(pubkey, bytes(row[6]), bytes(row[8]), signing_algorithm)
            )
        except (RuntimeError, ValueError):
            sig_valid = False

        return ProvenanceOut(
            belief=belief,
            source=source,
            agent_name=agent_name,
            parents=parents,
            children=children,
            chain_position=row[2],
            chain_valid=chain_valid,
            sig_valid=sig_valid,
        )

    result = run_tenant_txn(principal.tenant_id, txn)
    ms = int((time.perf_counter() - t0) * 1000)
    response.headers.append("X-Recant-Primitive", f"SERIALIZABLE TXN | {ms}ms")
    return result

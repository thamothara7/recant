"""forensics-api: read-only queries for custody inspection and time travel (spec section 5).

Provides AS OF SYSTEM TIME queries (proof moment 5), custody-chain reads,
incident summaries, and text-template incident affidavits. All endpoints
are read-only. The Bedrock Claude integration for AI-generated affidavits
arrives with U3 (AWS credentials).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg import sql

from services.attest_gateway import chain
from services.attest_gateway.signer import dev_action_signer_for, verify_signature
from services.common.config import cors_origins
from services.common.db import get_pool, run_txn
from services.common.logging import bind_incident, configure
from services.forensics.affidavit import (
    generate_affidavit,
    generate_affidavit_text,  # noqa: F401  (re-export; unit tests import from here)
)
from services.forensics.archive import MissingBucket, S3EvidenceArchiver
from services.forensics.models import (
    ActionOut,
    AffidavitOut,
    ArchiveOut,
    BeliefSnapshot,
    BeliefsPage,
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

def _run_read_txn(fn, *, as_of: datetime | None = None):
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
            return fn(conn)


_BELIEF_COLS = (
    "b.belief_id, b.agent_id, b.seq, b.content, b.status::text, b.created_at,"
    " b.hash, b.prev_hash, b.sig, b.source_id"
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
    )


def _require_agent(conn: psycopg.Connection, agent_id: UUID):
    row = conn.execute(
        "SELECT name, pubkey, head_hash, head_seq FROM agents WHERE agent_id = %s",
        (agent_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    return row


def _derivations_for(
    conn: psycopg.Connection, belief_id: UUID
) -> tuple[list[DerivationOut], list[DerivationOut]]:
    """Return (parents, children) derivation edges for a belief."""
    rows = conn.execute(
        "SELECT child_id, parent_id, kind, score FROM derivations"
        " WHERE child_id = %s OR parent_id = %s",
        (belief_id, belief_id),
    ).fetchall()
    parents = [
        DerivationOut(child_id=r[0], parent_id=r[1], kind=r[2], score=r[3])
        for r in rows
        if r[0] == belief_id
    ]
    children = [
        DerivationOut(child_id=r[0], parent_id=r[1], kind=r[2], score=r[3])
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
    except Exception:
        raise HTTPException(status_code=503, detail="database unreachable")
    return {"status": "ok"}


@app.get("/agents/{agent_id}/beliefs", response_model=BeliefsPage)
def agent_beliefs(agent_id: UUID, response: Response, as_of: datetime | None = None):
    """Belief set for an agent, optionally at a past timestamp (AOST).

    This is Proof Moment 5: side-by-side "what agent B believed at 14:32 vs now".
    When ``as_of`` is provided, the query runs inside a read-only transaction with
    ``SET TRANSACTION AS OF SYSTEM TIME``, CockroachDB's time-travel primitive.
    FastAPI parses ``as_of`` as a datetime, so garbage input gets a 422 before
    any SQL runs.
    """
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        agent_row = _require_agent(conn, agent_id)
        agent_name = agent_row[0]
        rows = conn.execute(
            f"SELECT {_BELIEF_COLS} FROM beliefs b"
            " WHERE b.agent_id = %s ORDER BY b.seq",
            (agent_id,),
        ).fetchall()
        return agent_name, rows

    agent_name, rows = _run_read_txn(txn, as_of=as_of)
    beliefs = [_belief_snapshot(r) for r in rows]
    as_of_str = as_of.isoformat() if as_of else None

    if as_of:
        ms = int((time.perf_counter() - t0) * 1000)
        response.headers.append("X-Recant-Primitive", f"AOST @ {as_of_str} | {ms}ms")
        log.info(
            "aost query",
            extra={"fields": {
                "agent_id": str(agent_id),
                "as_of": as_of_str,
                "count": len(beliefs),
                "ms": ms,
            }},
        )

    return BeliefsPage(
        agent_id=agent_id,
        agent_name=agent_name,
        as_of=as_of_str,
        beliefs=beliefs,
        count=len(beliefs),
    )


@app.get("/agents/{agent_id}/custody-chain", response_model=CustodyChainOut)
def custody_chain(agent_id: UUID, response: Response):
    """Full custody chain with derivation edges and chain verification."""
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        agent_row = _require_agent(conn, agent_id)
        agent_name, pubkey, head_hash, head_seq = agent_row

        rows = conn.execute(
            f"SELECT {_BELIEF_COLS} FROM beliefs b"
            " WHERE b.agent_id = %s ORDER BY b.seq",
            (agent_id,),
        ).fetchall()

        steps: list[CustodyStep] = []
        for r in rows:
            belief = _belief_snapshot(r)
            parents, children = _derivations_for(conn, r[0])
            steps.append(CustodyStep(belief=belief, parents=parents, children=children))

        # Verify the hash chain
        records = [
            chain.ChainRecord(
                agent_id=agent_id,
                seq=r[2],
                content=r[3],
                source_id=r[9],
                parent_ids=[
                    d.parent_id
                    for d in steps[i].parents
                    if d.kind == "explicit"
                ],
                ts=r[5],
                hash=bytes(r[6]),
            )
            for i, r in enumerate(rows)
        ]
        valid, _ = chain.verify_chain(records)

        # Also verify signatures
        if valid and records:
            pubkey_bytes = bytes(pubkey)
            for record, r in zip(records, rows):
                if not verify_signature(pubkey_bytes, record.hash, bytes(r[8])):
                    valid = False
                    break

        return agent_name, steps, valid

    agent_name, steps, valid = run_txn(txn)
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
def incident_summary(incident_id: UUID, response: Response):
    """Incident summary with source, closure, actions, and event timeline."""
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        # Incident + source
        row = conn.execute(
            "SELECT i.incident_id, i.source_id, i.opened_by, i.created_at,"
            " s.kind, s.uri, s.trust_tier"
            " FROM incidents i JOIN sources s ON i.source_id = s.source_id"
            " WHERE i.incident_id = %s",
            (incident_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown incident")
        inc_id, source_id, opened_by, created_at, s_kind, s_uri, s_tier = row

        # Quarantine actions
        action_rows = conn.execute(
            "SELECT action_id, belief_count, actor, sig, newly_flipped_ids, created_at"
            " FROM quarantine_actions WHERE incident_id = %s ORDER BY created_at",
            (incident_id,),
        ).fetchall()

        actions: list[ActionOut] = []
        all_flipped: list[UUID] = []
        for ar in action_rows:
            a_id, a_count, actor, sig, flipped, a_ts = ar
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
                )
                expected_pub = dev_action_signer_for(actor).public_key_bytes()
                sig_valid = verify_signature(
                    expected_pub, action_digest(payload), sig_bytes
                )
            except Exception:
                sig_valid = False

            actions.append(ActionOut(
                action_id=a_id,
                belief_count=a_count,
                actor=actor,
                sig=sig_bytes.hex(),
                newly_flipped_ids=flipped_ids,
                created_at=a_ts,
                sig_valid=sig_valid,
            ))

        # Per-agent affected counts
        agents_affected: list[dict] = []
        if all_flipped:
            agent_rows = conn.execute(
                "SELECT a.agent_id, a.name, count(*) FROM beliefs b"
                " JOIN agents a ON b.agent_id = a.agent_id"
                " WHERE b.belief_id = ANY(%s) GROUP BY a.agent_id, a.name",
                (all_flipped,),
            ).fetchall()
            agents_affected = [
                {"agent_id": str(r[0]), "agent_name": r[1], "belief_count": r[2]}
                for r in agent_rows
            ]

        # Events timeline
        event_rows = conn.execute(
            "SELECT event_id, kind, created_at, payload FROM memory_events"
            " WHERE incident_id = %s ORDER BY created_at",
            (incident_id,),
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

    result = run_txn(txn)
    ms = int((time.perf_counter() - t0) * 1000)
    response.headers.append("X-Recant-Primitive", f"SERIALIZABLE TXN | {ms}ms")
    with bind_incident(str(incident_id)):
        log.info(
            "incident summary",
            extra={"fields": {"closure_size": result.closure_size, "ms": ms}},
        )
    return result


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
            "summary": json.dumps(
                evt.payload.get("evictions", []), default=str
            )[:80]
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
def affidavit(incident_id: UUID, response: Response):
    """Forensic affidavit from the incident records.

    RECANT_AFFIDAVIT selects the generator: the deterministic text template
    (default; offline and used by tests) or Bedrock Claude, which writes the
    affidavit from the same structured facts and falls back to the template
    on any Bedrock failure.
    """
    # Reuse the incident summary logic
    summary = incident_summary(incident_id, response)
    text, generated_by = generate_affidavit(_affidavit_structured(incident_id, summary))
    return AffidavitOut(incident_id=incident_id, generated_by=generated_by, text=text)


@app.post("/incidents/{incident_id}/archive", response_model=ArchiveOut)
def archive(incident_id: UUID, response: Response):
    """Write the incident's evidence bundle to S3 (W4 archive leg).

    The bundle is everything a DB-less verifier needs under one prefix:
    the incident summary (with per-action signature verdicts), the
    affidavit, and the custody chain of every affected agent. The database
    is only read; the side effect is the S3 write.
    """
    summary = incident_summary(incident_id, response)
    text, generated_by = generate_affidavit(_affidavit_structured(incident_id, summary))

    documents: dict[str, tuple[str, str]] = {
        "incident.json": (summary.model_dump_json(indent=2), "application/json"),
        "affidavit.txt": (text, "text/plain; charset=utf-8"),
    }
    for agent in summary.agents_affected:
        chain_out = custody_chain(UUID(agent["agent_id"]), response)
        documents[f"custody/{agent['agent_id']}.json"] = (
            chain_out.model_dump_json(indent=2),
            "application/json",
        )

    archiver = S3EvidenceArchiver()
    try:
        keys = archiver.put_bundle(incident_id, documents)
        bucket = archiver.bucket
    except MissingBucket as exc:
        raise HTTPException(status_code=503, detail=str(exc))

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
def provenance(belief_id: UUID, response: Response):
    """Single belief provenance: parents, source, chain position, verification."""
    t0 = time.perf_counter()

    def txn(conn: psycopg.Connection):
        row = conn.execute(
            f"SELECT {_BELIEF_COLS} FROM beliefs b WHERE b.belief_id = %s",
            (belief_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown belief")

        belief = _belief_snapshot(row)
        agent_id = row[1]

        # Agent name + pubkey
        agent_row = conn.execute(
            "SELECT name, pubkey FROM agents WHERE agent_id = %s",
            (agent_id,),
        ).fetchone()
        agent_name = agent_row[0]
        pubkey = bytes(agent_row[1])

        # Source info
        source = None
        if row[9]:  # source_id
            src = conn.execute(
                "SELECT source_id, kind, uri, trust_tier FROM sources WHERE source_id = %s",
                (row[9],),
            ).fetchone()
            if src:
                source = {
                    "source_id": str(src[0]),
                    "kind": src[1],
                    "uri": src[2],
                    "trust_tier": src[3],
                }

        # Derivations
        parents, children = _derivations_for(conn, belief_id)

        # Verify the chain hash for this specific belief
        explicit_parent_ids = [d.parent_id for d in parents if d.kind == "explicit"]
        prev_hash = bytes(row[7]) if row[7] else chain.GENESIS
        payload = chain.canonical_payload(
            agent_id=agent_id,
            seq=row[2],
            content=row[3],
            source_id=row[9],
            parent_ids=explicit_parent_ids,
            ts=row[5],
        )
        expected_hash = chain.chain_hash(prev_hash, payload)
        chain_valid = expected_hash == bytes(row[6])

        # Verify signature
        sig_valid = verify_signature(pubkey, bytes(row[6]), bytes(row[8]))

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

    result = run_txn(txn)
    ms = int((time.perf_counter() - t0) * 1000)
    response.headers.append("X-Recant-Primitive", f"SERIALIZABLE TXN | {ms}ms")
    return result

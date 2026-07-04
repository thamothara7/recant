"""attest-gateway: the only write path into Recant memory (spec section 5).

Every belief write happens in one serializable transaction that reads the agent's
chain head FOR UPDATE (serializing appends per agent), computes the chain hash,
signs it, inserts the belief plus explicit derivation edges, and advances the head.
"""

import os
import time
from datetime import timedelta
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from services.attest_gateway import chain
from services.attest_gateway.models import (
    AgentIn,
    AgentOut,
    BeliefIn,
    BeliefOut,
    ChainVerification,
    SourceIn,
    SourceOut,
)
from services.attest_gateway.signer import dev_signer_for, verify_signature
from services.common.config import cors_origins
from services.common.db import run_txn
from services.common.vectors import to_vector_literal

# Env-configurable: TTL deletes are blocked by derivation FKs anyway (rows
# persist, job errors — README failure-modes table), and the deployed demo must
# outlive the judging window, so W6 sets this to 90 (design review 2026-07-03).
UNTRUSTED_TTL = timedelta(days=float(os.environ.get("RECANT_UNTRUSTED_TTL_DAYS", "7")))

app = FastAPI(title="recant attest-gateway")

# Proof moment 1 (attested write) chip: the console fetches X-Recant-Primitive
# cross-origin from localhost:5173, so it must be CORS-exposed here just as the
# quarantine service exposes it (review 2026-07-03).
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Recant-Primitive"],
)


@app.middleware("http")
async def judge_overlay_header(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    if request.method == "POST" and request.url.path == "/beliefs" and response.status_code < 400:
        ms = int((time.perf_counter() - t0) * 1000)
        response.headers["X-Recant-Primitive"] = f"SERIALIZABLE TXN | {ms}ms"
    return response


@app.get("/healthz")
def healthz():
    try:
        run_txn(lambda conn: conn.execute("SELECT 1").fetchone())
    except Exception:
        raise HTTPException(status_code=503, detail="database unreachable")
    return {"status": "ok"}


@app.post("/agents", response_model=AgentOut, status_code=201)
def create_agent(body: AgentIn) -> AgentOut:
    pubkey = dev_signer_for(body.name).public_key_bytes()

    def txn(conn: psycopg.Connection):
        return conn.execute(
            "INSERT INTO agents (name, pubkey, region) VALUES (%s, %s, %s) RETURNING agent_id",
            (body.name, pubkey, body.region),
        ).fetchone()[0]

    try:
        agent_id = run_txn(txn)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"agent name already exists: {body.name}")
    return AgentOut(agent_id=agent_id, name=body.name, pubkey=pubkey.hex(), region=body.region)


@app.post("/sources", response_model=SourceOut, status_code=201)
def create_source(body: SourceIn) -> SourceOut:
    def txn(conn: psycopg.Connection):
        return conn.execute(
            "INSERT INTO sources (kind, uri, trust_tier, region) VALUES (%s, %s, %s, %s) RETURNING source_id",
            (body.kind, body.uri, body.trust_tier, body.region),
        ).fetchone()[0]

    source_id = run_txn(txn)
    return SourceOut(source_id=source_id, kind=body.kind, uri=body.uri, trust_tier=body.trust_tier)


@app.post("/beliefs", response_model=BeliefOut, status_code=201)
def create_belief(body: BeliefIn) -> BeliefOut:
    parent_ids = list(dict.fromkeys(body.parent_ids))

    def txn(conn: psycopg.Connection) -> BeliefOut:
        # One clock domain: stamp created_at from the DATABASE clock, same source
        # as sources.created_at (DEFAULT now()). The taint window compares the two
        # (engine.py), so a client wall clock would let host/DB skew shift the
        # contamination boundary (review 2026-07-03). now() is the txn timestamp,
        # stable across a 40001 retry within the attempt.
        ts = conn.execute("SELECT now()").fetchone()[0]
        row = conn.execute(
            "SELECT name, head_hash, head_seq FROM agents WHERE agent_id = %s FOR UPDATE",
            (body.agent_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown agent")
        name, head_hash, head_seq = row

        ttl_expire_at = None
        if body.source_id is not None:
            src = conn.execute(
                "SELECT trust_tier FROM sources WHERE source_id = %s", (body.source_id,)
            ).fetchone()
            if src is None:
                raise HTTPException(status_code=422, detail="unknown source")
            if src[0] == "untrusted":
                ttl_expire_at = ts + UNTRUSTED_TTL

        # Post-recant residue check (design review 2026-07-03): a new belief
        # citing a recanted source or deriving from a quarantined parent is born
        # 'suspect' rather than 'active'. This is the write-path half of the
        # residue story; the W3 changefeed eviction is the runtime half.
        status = "active"
        if body.source_id is not None:
            if conn.execute(
                "SELECT 1 FROM incidents WHERE source_id = %s LIMIT 1", (body.source_id,)
            ).fetchone():
                status = "suspect"
        if status == "active" and parent_ids:
            tainted_parent = conn.execute(
                "SELECT 1 FROM beliefs WHERE belief_id = ANY(%s)"
                " AND status IN ('suspect', 'quarantined') LIMIT 1",
                (parent_ids,),
            ).fetchone()
            if tainted_parent:
                status = "suspect"

        prev = bytes(head_hash) if head_hash is not None else chain.GENESIS
        seq = int(head_seq) + 1
        payload = chain.canonical_payload(
            agent_id=body.agent_id,
            seq=seq,
            content=body.content,
            source_id=body.source_id,
            parent_ids=parent_ids,
            ts=ts,
        )
        h = chain.chain_hash(prev, payload)
        sig = dev_signer_for(name).sign(h)
        emb = to_vector_literal(body.embedding) if body.embedding is not None else None

        belief_id = conn.execute(
            """
            INSERT INTO beliefs
                (agent_id, seq, content, embedding, status, created_at, sig, prev_hash,
                 hash, source_id, ttl_expire_at)
            VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s)
            RETURNING belief_id
            """,
            (body.agent_id, seq, body.content, emb, status, ts, sig, prev, h,
             body.source_id, ttl_expire_at),
        ).fetchone()[0]

        for pid in parent_ids:
            conn.execute(
                "INSERT INTO derivations (child_id, parent_id, kind, score) VALUES (%s, %s, 'explicit', 1.0)",
                (belief_id, pid),
            )

        conn.execute(
            "UPDATE agents SET head_hash = %s, head_seq = %s WHERE agent_id = %s",
            (h, seq, body.agent_id),
        )
        return BeliefOut(
            belief_id=belief_id,
            agent_id=body.agent_id,
            seq=seq,
            content=body.content,
            status=status,
            created_at=ts,
            hash=h.hex(),
            prev_hash=prev.hex(),
            sig=sig.hex(),
        )

    try:
        return run_txn(txn)
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(status_code=422, detail="unknown parent belief")


@app.get("/agents/{agent_id}/chain/verify", response_model=ChainVerification)
def verify_agent_chain(agent_id: UUID) -> ChainVerification:
    def txn(conn: psycopg.Connection):
        agent_row = conn.execute(
            "SELECT pubkey, head_hash, head_seq FROM agents WHERE agent_id = %s",
            (agent_id,),
        ).fetchone()
        if agent_row is None:
            raise HTTPException(status_code=404, detail="unknown agent")
        rows = conn.execute(
            """
            SELECT b.seq, b.content, b.source_id, b.created_at, b.hash, b.sig,
                   (SELECT array_agg(d.parent_id) FROM derivations d
                    WHERE d.child_id = b.belief_id AND d.kind = 'explicit')
            FROM beliefs b
            WHERE b.agent_id = %s
            ORDER BY b.seq
            """,
            (agent_id,),
        ).fetchall()
        return agent_row, rows

    agent_row, rows = run_txn(txn)
    pubkey, head_hash, head_seq = agent_row
    pubkey = bytes(pubkey)
    head_hash = bytes(head_hash) if head_hash is not None else None
    head_seq = int(head_seq)

    records = [
        chain.ChainRecord(
            agent_id=agent_id,
            seq=r[0],
            content=r[1],
            source_id=r[2],
            parent_ids=list(r[6] or []),
            ts=r[3],
            hash=bytes(r[4]),
        )
        for r in rows
    ]
    sigs = [bytes(r[5]) for r in rows]

    valid, bad = chain.verify_chain(records)
    reason: str | None = None
    if not valid:
        reason = "hash_mismatch"
    else:
        for i, (record, sig) in enumerate(zip(records, sigs)):
            if not verify_signature(pubkey, record.hash, sig):
                valid = False
                bad = i
                reason = "bad_signature"
                break

    first_invalid_seq = None if valid else records[bad].seq

    if valid:
        if records:
            last = records[-1]
            if last.seq != head_seq or last.hash != head_hash:
                valid = False
                reason = "truncated"
                first_invalid_seq = head_seq
        elif head_seq != 0:
            valid = False
            reason = "truncated"
            first_invalid_seq = head_seq

    return ChainVerification(
        agent_id=agent_id,
        length=len(records),
        valid=valid,
        first_invalid_seq=first_invalid_seq,
        reason=reason,
    )

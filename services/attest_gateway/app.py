"""The only supported write path into Recant memory.

Beliefs are appended under a per-agent serializable lock, signed, assigned a
non-amplifying authority rank, and linked to every source captured by a signed
context receipt. Production requests are tenant-scoped by both application
identity and CockroachDB row-level security.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
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
from services.attest_gateway.signer import (
    control_signer_for,
    signer_for_agent,
    verify_signature,
)
from services.common.attestation import canonical_json, sha256
from services.common.auth import Principal, require_roles
from services.common.authority import rank_for_trust_tier
from services.common.config import cors_origins
from services.common.db import run_tenant_txn, run_txn
from services.common.embedder import Embedder, select_embedder
from services.common.idempotency import replay, request_hash, store, validate_key
from services.common.vectors import to_vector_literal
from services.guard.beliefs import (
    BeliefTrustUnavailable,
    BeliefVerificationError,
    VerifiedBelief,
    load_verified_beliefs,
)
from services.guard.crypto import context_receipt_payload

UNTRUSTED_TTL = timedelta(days=float(os.environ.get("RECANT_UNTRUSTED_TTL_DAYS", "7")))

_embedder: Embedder | None = None


def _content_embedding(content: str) -> list[float]:
    global _embedder
    if _embedder is None:
        try:
            _embedder = select_embedder()
        except ValueError as exc:
            raise HTTPException(
                status_code=503, detail="embedding configuration is invalid"
            ) from exc
    try:
        return _embedder.embed(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="embedding provider unavailable") from exc


def _provenance_required() -> bool:
    raw = os.environ.get("RECANT_REQUIRE_PROVENANCE")
    normalized = raw.strip().lower() if raw is not None else None
    truthy = {"1", "true", "yes", "on"}
    falsey = {"0", "false", "no", "off"}
    if normalized not in {None, *truthy, *falsey}:
        raise RuntimeError("RECANT_REQUIRE_PROVENANCE must be a boolean value")
    if os.environ.get("RECANT_ENV", "").strip().lower() == "production":
        return True
    return normalized in truthy


def _verify_source_assertion(
    *, source_id: UUID, tenant_id: UUID, row: tuple, trusted_signer
) -> None:
    (
        trust_tier,
        authority_rank,
        kind,
        uri,
        region,
        issuer,
        created_at,
        sig,
        pubkey,
        algorithm,
        key_id,
    ) = row
    if sig is None or pubkey is None or algorithm is None or key_id is None:
        if os.environ.get("RECANT_ENV", "").strip().lower() == "production":
            raise HTTPException(status_code=409, detail="source has no trusted authority assertion")
        return
    payload = _source_assertion_payload(
        source_id=source_id,
        tenant_id=tenant_id,
        kind=kind,
        uri=uri,
        trust_tier=trust_tier,
        authority_rank=int(authority_rank),
        region=region,
        issuer=issuer,
        created_at=created_at,
    )
    if (
        key_id != trusted_signer.key_id
        or algorithm != trusted_signer.algorithm
        or bytes(pubkey) != trusted_signer.public_key_bytes()
        or not verify_signature(bytes(pubkey), sha256(payload), bytes(sig), algorithm)
    ):
        raise HTTPException(status_code=409, detail="source authority assertion is invalid")


def _source_assertion_payload(
    *,
    source_id: UUID,
    tenant_id: UUID,
    kind: str,
    uri: str,
    trust_tier: str,
    authority_rank: int,
    region: str,
    issuer: str,
    created_at,
) -> bytes:
    return canonical_json(
        {
            "type": "recant.source-assertion.v1",
            "source_id": source_id,
            "tenant_id": tenant_id,
            "kind": kind,
            "uri": uri,
            "trust_tier": trust_tier,
            "authority_rank": authority_rank,
            "region": region,
            "issuer": issuer,
            "created_at": created_at,
        }
    )


app = FastAPI(title="recant attest-gateway")
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
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unreachable") from exc
    return {"status": "ok"}


@app.post("/agents", response_model=AgentOut, status_code=201)
def create_agent(
    body: AgentIn,
    principal: Principal = Depends(require_roles("writer")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AgentOut:
    key = validate_key(idempotency_key)
    digest = request_hash(body)
    try:
        signer = signer_for_agent(body.name, body.kms_key_arn)
        pubkey = signer.public_key_bytes()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    agent_id = uuid4()

    def txn(conn: psycopg.Connection) -> AgentOut:
        prior = replay(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/agents",
            key=key,
            digest=digest,
        )
        if prior is not None:
            return AgentOut.model_validate(prior)
        conn.execute(
            "INSERT INTO agents"
            " (agent_id, tenant_id, name, pubkey, kms_key_arn, signing_algorithm, region)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                agent_id,
                principal.tenant_id,
                body.name,
                pubkey,
                body.kms_key_arn,
                signer.algorithm,
                body.region,
            ),
        )
        result = AgentOut(
            agent_id=agent_id,
            name=body.name,
            pubkey=pubkey.hex(),
            region=body.region,
            signing_algorithm=signer.algorithm,
            signer_key_id=signer.key_id,
        )
        store(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/agents",
            key=key,
            digest=digest,
            response_status=201,
            response_body=result.model_dump(mode="json"),
        )
        return result

    try:
        return run_tenant_txn(principal.tenant_id, txn)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409, detail=f"agent name already exists: {body.name}"
        ) from exc


@app.post("/sources", response_model=SourceOut, status_code=201)
def create_source(
    body: SourceIn,
    principal: Principal = Depends(require_roles("writer", "source_admin")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SourceOut:
    if body.trust_tier in {"verified", "partner"} and not principal.has_any("source_admin"):
        raise HTTPException(
            status_code=403,
            detail="source_admin is required to assign partner or verified trust",
        )
    key = validate_key(idempotency_key)
    digest = request_hash(body)
    authority_rank = rank_for_trust_tier(body.trust_tier)
    source_id = uuid4()
    try:
        signer = control_signer_for("source-authority")
        pubkey = signer.public_key_bytes()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def txn(conn: psycopg.Connection) -> SourceOut:
        prior = replay(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/sources",
            key=key,
            digest=digest,
        )
        if prior is not None:
            return SourceOut.model_validate(prior)
        created_row = conn.execute("SELECT now()").fetchone()
        assert created_row is not None
        created_at = created_row[0]
        assertion = _source_assertion_payload(
            source_id=source_id,
            tenant_id=principal.tenant_id,
            kind=body.kind,
            uri=body.uri,
            trust_tier=body.trust_tier,
            authority_rank=authority_rank,
            region=body.region,
            issuer=principal.subject,
            created_at=created_at,
        )
        sig = signer.sign(sha256(assertion))
        conn.execute(
            "INSERT INTO sources"
            " (source_id, tenant_id, kind, uri, trust_tier, authority_rank, region,"
            " issuer_principal_id, issuer_subject, assertion_sig, assertion_pubkey,"
            " signing_algorithm, signer_key_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                source_id,
                principal.tenant_id,
                body.kind,
                body.uri,
                body.trust_tier,
                authority_rank,
                body.region,
                principal.principal_id,
                principal.subject,
                sig,
                pubkey,
                signer.algorithm,
                signer.key_id,
                created_at,
            ),
        )
        result = SourceOut(
            source_id=source_id,
            kind=body.kind,
            uri=body.uri,
            trust_tier=body.trust_tier,
            authority_rank=authority_rank,
            issuer=principal.subject,
        )
        store(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/sources",
            key=key,
            digest=digest,
            response_status=201,
            response_body=result.model_dump(mode="json"),
        )
        return result

    return run_tenant_txn(principal.tenant_id, txn)


@app.post("/beliefs", response_model=BeliefOut, status_code=201)
def create_belief(
    body: BeliefIn,
    principal: Principal = Depends(require_roles("writer")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BeliefOut:
    declared_parent_ids = list(dict.fromkeys(body.parent_ids))
    if _provenance_required() and declared_parent_ids and body.context_receipt_id is None:
        raise HTTPException(
            status_code=422,
            detail="a signed context_receipt_id is required for derived memories",
        )
    if (
        _provenance_required()
        and body.source_id is None
        and not declared_parent_ids
        and body.context_receipt_id is None
    ):
        raise HTTPException(
            status_code=422,
            detail="production beliefs require a source or signed context receipt",
        )
    key = validate_key(idempotency_key)
    digest = request_hash(body)
    embedding = body.embedding if body.embedding is not None else _content_embedding(body.content)
    trusted_source_signer = None
    trusted_receipt_signer = None
    try:
        if body.source_id is not None:
            trusted_source_signer = control_signer_for("source-authority")
        if body.context_receipt_id is not None:
            trusted_receipt_signer = control_signer_for("guard")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def txn(conn: psycopg.Connection) -> BeliefOut:
        prior = replay(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/beliefs",
            key=key,
            digest=digest,
        )
        if prior is not None:
            return BeliefOut.model_validate(prior)

        timestamp_row = conn.execute("SELECT now()").fetchone()
        assert timestamp_row is not None
        ts = timestamp_row[0]
        row = conn.execute(
            "SELECT name, head_hash, head_seq, kms_key_arn, signing_algorithm"
            " FROM agents WHERE tenant_id = %s AND agent_id = %s FOR UPDATE",
            (principal.tenant_id, body.agent_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown agent")
        name, head_hash, head_seq, kms_key_arn, signing_algorithm = row

        receipt_parent_ids: list[UUID] = []
        if body.context_receipt_id is not None:
            receipt = conn.execute(
                "SELECT agent_id, issued_to, belief_ids, belief_hashes, origin_source_ids,"
                " authority_rank, payload_hash, sig, signer_pubkey, signing_algorithm,"
                " signer_key_id, created_at, expires_at FROM context_receipts"
                " WHERE tenant_id = %s AND receipt_id = %s AND expires_at > now()",
                (principal.tenant_id, body.context_receipt_id),
            ).fetchone()
            if receipt is None:
                raise HTTPException(status_code=422, detail="unknown or expired context receipt")
            (
                receipt_agent_id,
                issued_to,
                receipt_ids,
                belief_hashes,
                receipt_origins,
                receipt_authority,
                payload_hash,
                receipt_sig,
                receipt_pubkey,
                receipt_algorithm,
                receipt_key_id,
                receipt_created_at,
                receipt_expires_at,
            ) = receipt
            if receipt_agent_id != body.agent_id:
                raise HTTPException(
                    status_code=422, detail="context receipt belongs to another agent"
                )
            if issued_to is not None and issued_to != principal.principal_id:
                raise HTTPException(
                    status_code=403, detail="context receipt belongs to another principal"
                )
            receipt_parent_ids = list(receipt_ids or [])
            receipt_payload = context_receipt_payload(
                receipt_id=body.context_receipt_id,
                tenant_id=principal.tenant_id,
                agent_id=body.agent_id,
                issued_to=issued_to,
                belief_ids=receipt_parent_ids,
                belief_hashes=list(belief_hashes or []),
                origin_source_ids=list(receipt_origins or []),
                authority_rank=int(receipt_authority),
                created_at=receipt_created_at,
                expires_at=receipt_expires_at,
            )
            expected = sha256(receipt_payload)
            assert trusted_receipt_signer is not None
            if (
                receipt_key_id != trusted_receipt_signer.key_id
                or receipt_algorithm != trusted_receipt_signer.algorithm
                or bytes(receipt_pubkey) != trusted_receipt_signer.public_key_bytes()
                or bytes(payload_hash) != expected
                or not verify_signature(
                    bytes(receipt_pubkey), expected, bytes(receipt_sig), receipt_algorithm
                )
            ):
                raise HTTPException(status_code=409, detail="context receipt signature is invalid")
            if declared_parent_ids and not set(declared_parent_ids).issubset(receipt_parent_ids):
                raise HTTPException(
                    status_code=422,
                    detail="declared parents are not covered by the context receipt",
                )

        parent_ids = list(dict.fromkeys(declared_parent_ids + receipt_parent_ids))
        if len(parent_ids) > 64:
            raise HTTPException(status_code=422, detail="a belief can have at most 64 parents")

        parent_rows: list[VerifiedBelief] = []
        if parent_ids:
            try:
                parent_rows = load_verified_beliefs(
                    conn, tenant_id=principal.tenant_id, belief_ids=parent_ids
                )
            except BeliefTrustUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except BeliefVerificationError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if len(parent_rows) != len(parent_ids):
                raise HTTPException(status_code=422, detail="unknown parent belief")
        parent_by_id = {row.belief_id: row for row in parent_rows}
        if receipt_parent_ids:
            current_receipt_rows = [parent_by_id[value] for value in receipt_parent_ids]
            current_hashes = [row.hash_hex for row in current_receipt_rows]
            current_origins = sorted(
                {source_id for row in current_receipt_rows for source_id in row.origin_source_ids},
                key=str,
            )
            current_authority = min(row.authority_rank for row in current_receipt_rows)
            if (
                any(row.status != "active" for row in current_receipt_rows)
                or current_hashes != list(belief_hashes or [])
                or current_origins != list(receipt_origins or [])
                or current_authority != int(receipt_authority)
            ):
                raise HTTPException(
                    status_code=409, detail="context receipt evidence is no longer valid"
                )

        ttl_expire_at = None
        source_rank: int | None = None
        source_origins: set[UUID] = set()
        if body.source_id is not None:
            src = conn.execute(
                "SELECT trust_tier, authority_rank, kind, uri, region, issuer_subject, created_at,"
                " assertion_sig, assertion_pubkey, signing_algorithm, signer_key_id FROM sources"
                " WHERE tenant_id = %s AND source_id = %s",
                (principal.tenant_id, body.source_id),
            ).fetchone()
            if src is None:
                raise HTTPException(status_code=422, detail="unknown source")
            assert trusted_source_signer is not None
            _verify_source_assertion(
                source_id=body.source_id,
                tenant_id=principal.tenant_id,
                row=src,
                trusted_signer=trusted_source_signer,
            )
            source_rank = int(src[1])
            source_origins.add(body.source_id)
            if src[0] == "untrusted":
                ttl_expire_at = ts + UNTRUSTED_TTL

        authority_inputs = ([source_rank] if source_rank is not None else []) + [
            parent.authority_rank for parent in parent_rows
        ]
        authority_rank = min(authority_inputs) if authority_inputs else 0
        origin_source_ids = set(source_origins)
        for parent in parent_rows:
            origin_source_ids.update(parent.origin_source_ids)

        status = "active"
        if (
            body.source_id is not None
            and conn.execute(
                "SELECT 1 FROM incidents WHERE tenant_id = %s AND source_id = %s LIMIT 1",
                (principal.tenant_id, body.source_id),
            ).fetchone()
        ):
            status = "suspect"
        if status == "active" and any(
            parent.status in {"suspect", "quarantined"} for parent in parent_rows
        ):
            status = "suspect"

        prev = bytes(head_hash) if head_hash is not None else chain.GENESIS
        seq = int(head_seq) + 1
        provenance_method = (
            "context_receipt"
            if body.context_receipt_id is not None
            else "declared"
            if parent_ids
            else "source"
            if body.source_id is not None
            else "unattributed"
        )
        sorted_origins = sorted(origin_source_ids, key=str)
        payload = chain.canonical_payload_v2(
            tenant_id=principal.tenant_id,
            agent_id=body.agent_id,
            seq=seq,
            content=body.content,
            source_id=body.source_id,
            parent_ids=parent_ids,
            context_receipt_id=body.context_receipt_id,
            authority_rank=authority_rank,
            origin_source_ids=sorted_origins,
            provenance_method=provenance_method,
            provenance_version="v1",
            ts=ts,
        )
        h = chain.chain_hash(prev, payload)
        try:
            signer = signer_for_agent(name, kms_key_arn)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if signer.algorithm != signing_algorithm:
            raise HTTPException(status_code=503, detail="agent signer configuration changed")
        sig = signer.sign(h)
        emb = to_vector_literal(embedding)
        belief_id = uuid4()

        conn.execute(
            "INSERT INTO beliefs"
            " (belief_id, tenant_id, agent_id, seq, content, embedding, status, created_at,"
            " sig, prev_hash, hash, source_id, ttl_expire_at, authority_rank,"
            " origin_source_ids, context_receipt_id, provenance_method, provenance_version,"
            " attestation_version)"
            " VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s, %s, 'v1', 'v2')",
            (
                belief_id,
                principal.tenant_id,
                body.agent_id,
                seq,
                body.content,
                emb,
                status,
                ts,
                sig,
                prev,
                h,
                body.source_id,
                ttl_expire_at,
                authority_rank,
                sorted_origins,
                body.context_receipt_id,
                provenance_method,
            ),
        )
        if body.source_id is not None:
            exact_matches = conn.execute(
                "SELECT belief_id FROM beliefs WHERE tenant_id = %s"
                " AND source_id IS NOT NULL AND belief_id != %s AND content = %s",
                (principal.tenant_id, belief_id, body.content),
            ).fetchall()
            for (other_id,) in exact_matches:
                conn.execute(
                    "UPSERT INTO semantic_relations"
                    " (tenant_id, left_belief_id, right_belief_id, relation, confidence,"
                    " evidence_method, evidence_version)"
                    " VALUES (%s, %s, %s, 'equivalent', 1.0, 'exact_content', 'v1')",
                    (principal.tenant_id, other_id, belief_id),
                )
        for parent_id in parent_ids:
            conn.execute(
                "INSERT INTO derivations"
                " (tenant_id, child_id, parent_id, kind, score, evidence_method, evidence_version)"
                " VALUES (%s, %s, %s, 'explicit', 1.0, %s, 'v1')",
                (
                    principal.tenant_id,
                    belief_id,
                    parent_id,
                    "context_receipt" if parent_id in receipt_parent_ids else "declared",
                ),
            )
        conn.execute(
            "UPDATE agents SET head_hash = %s, head_seq = %s"
            " WHERE tenant_id = %s AND agent_id = %s",
            (h, seq, principal.tenant_id, body.agent_id),
        )
        result = BeliefOut(
            belief_id=belief_id,
            agent_id=body.agent_id,
            seq=seq,
            content=body.content,
            status=status,
            created_at=ts,
            hash=h.hex(),
            prev_hash=prev.hex(),
            sig=sig.hex(),
            authority_rank=authority_rank,
            origin_source_ids=sorted_origins,
            context_receipt_id=body.context_receipt_id,
            provenance_method=provenance_method,
            provenance_version="v1",
            attestation_version="v2",
        )
        store(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/beliefs",
            key=key,
            digest=digest,
            response_status=201,
            response_body=result.model_dump(mode="json"),
        )
        return result

    try:
        return run_tenant_txn(principal.tenant_id, txn)
    except psycopg.errors.ForeignKeyViolation as exc:
        raise HTTPException(status_code=422, detail="unknown parent belief") from exc


@app.get("/agents/{agent_id}/chain/verify", response_model=ChainVerification)
def verify_agent_chain(
    agent_id: UUID,
    principal: Principal = Depends(require_roles("writer", "auditor")),
) -> ChainVerification:
    def txn(conn: psycopg.Connection):
        agent_row = conn.execute(
            "SELECT pubkey, head_hash, head_seq, signing_algorithm FROM agents"
            " WHERE tenant_id = %s AND agent_id = %s",
            (principal.tenant_id, agent_id),
        ).fetchone()
        if agent_row is None:
            raise HTTPException(status_code=404, detail="unknown agent")
        rows = conn.execute(
            "SELECT b.seq, b.content, b.source_id, b.created_at, b.prev_hash, b.hash, b.sig,"
            " (SELECT array_agg(d.parent_id) FROM derivations d"
            "  WHERE d.tenant_id = %s AND d.child_id = b.belief_id AND d.kind = 'explicit'),"
            " b.context_receipt_id, b.authority_rank, b.origin_source_ids,"
            " b.provenance_method, b.provenance_version, b.attestation_version"
            " FROM beliefs b WHERE b.tenant_id = %s AND b.agent_id = %s ORDER BY b.seq",
            (principal.tenant_id, principal.tenant_id, agent_id),
        ).fetchall()
        return agent_row, rows

    agent_row, rows = run_tenant_txn(principal.tenant_id, txn)
    pubkey, head_hash, head_seq, signing_algorithm = agent_row
    pubkey = bytes(pubkey)
    head_hash = bytes(head_hash) if head_hash is not None else None
    head_seq = int(head_seq)
    records = [
        chain.ChainRecord(
            agent_id=agent_id,
            seq=row[0],
            content=row[1],
            source_id=row[2],
            parent_ids=list(row[7] or []),
            ts=row[3],
            prev_hash=bytes(row[4]),
            hash=bytes(row[5]),
            tenant_id=principal.tenant_id,
            context_receipt_id=row[8],
            authority_rank=int(row[9]),
            origin_source_ids=list(row[10] or []),
            provenance_method=row[11],
            provenance_version=row[12],
            attestation_version=row[13],
        )
        for row in rows
    ]
    sigs = [bytes(row[6]) for row in rows]
    valid, bad = chain.verify_chain(records)
    reason: str | None = None
    if not valid:
        reason = "hash_mismatch"
    else:
        for index, (record, sig) in enumerate(zip(records, sigs, strict=True)):
            if not verify_signature(pubkey, record.hash, sig, signing_algorithm):
                valid = False
                bad = index
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
        elif head_seq != 0 or head_hash is not None:
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

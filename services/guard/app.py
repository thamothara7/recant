"""Recant Guard: proof-carrying memory authorization for consequential tools."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.types.json import Json

from services.attest_gateway.signer import control_signer_for, verify_signature
from services.common.attestation import sha256
from services.common.auth import Principal, auth_required, require_roles
from services.common.authority import USER_CONFIRMED, label_for_rank
from services.common.config import cors_origins
from services.common.db import run_tenant_txn, run_txn
from services.common.idempotency import replay, request_hash, store, validate_key
from services.guard.beliefs import (
    BeliefTrustUnavailable,
    BeliefVerificationError,
    VerifiedBelief,
    load_verified_beliefs,
)
from services.guard.crypto import (
    action_digest,
    context_receipt_payload,
    decision_payload,
    decode_permit,
    encode_permit,
    permit_payload,
)
from services.guard.models import (
    AuthorizeIn,
    ConfirmIn,
    ConsumeIn,
    ConsumeOut,
    ContextReceiptIn,
    ContextReceiptOut,
    DecisionOut,
    RelationVerifyIn,
    RelationVerifyOut,
    ToolPolicyIn,
    ToolPolicyOut,
)
from services.guard.policy import ToolPolicy, resolve_policy
from services.taint_engine.relations import select_claim_verifier

PERMIT_TTL_SECONDS = min(max(int(os.environ.get("RECANT_PERMIT_TTL_SECONDS", "60")), 10), 300)
DecisionVerdict = Literal["allow", "confirm", "deny"]

app = FastAPI(title="recant guard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Recant-Primitive"],
)


@app.get("/healthz")
def healthz():
    try:
        run_txn(lambda conn: conn.execute("SELECT 1").fetchone())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unreachable") from exc
    return {"status": "ok"}


def _control_signer():
    try:
        return control_signer_for("guard")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _verified_support(
    conn: psycopg.Connection, *, tenant_id: UUID, belief_ids: list[UUID]
) -> list[VerifiedBelief]:
    try:
        return load_verified_beliefs(conn, tenant_id=tenant_id, belief_ids=belief_ids)
    except BeliefTrustUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BeliefVerificationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _load_context_receipt(
    conn: psycopg.Connection,
    *,
    principal: Principal,
    receipt_id: UUID,
    agent_id: UUID,
    trusted_signer,
    expected_issued_to: UUID | None,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT issued_to, belief_ids, belief_hashes, origin_source_ids, authority_rank,"
        " payload_hash, sig, signer_pubkey, signing_algorithm, signer_key_id,"
        " created_at, expires_at FROM context_receipts"
        " WHERE tenant_id = %s AND receipt_id = %s AND agent_id = %s AND expires_at > now()",
        (principal.tenant_id, receipt_id, agent_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=422, detail="unknown or expired context receipt")
    (
        issued_to,
        belief_ids,
        belief_hashes,
        origins,
        authority_rank,
        payload_hash,
        sig,
        pubkey,
        algorithm,
        key_id,
        created_at,
        expires_at,
    ) = row
    if issued_to is not None and issued_to != expected_issued_to:
        raise HTTPException(status_code=403, detail="context receipt belongs to another principal")
    belief_ids = list(belief_ids or [])
    belief_hashes = list(belief_hashes or [])
    origins = list(origins or [])
    payload = context_receipt_payload(
        receipt_id=receipt_id,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        issued_to=issued_to,
        belief_ids=belief_ids,
        belief_hashes=belief_hashes,
        origin_source_ids=origins,
        authority_rank=int(authority_rank),
        created_at=created_at,
        expires_at=expires_at,
    )
    digest = sha256(payload)
    if (
        key_id != trusted_signer.key_id
        or algorithm != trusted_signer.algorithm
        or bytes(pubkey) != trusted_signer.public_key_bytes()
        or bytes(payload_hash) != digest
        or not verify_signature(bytes(pubkey), digest, bytes(sig), algorithm)
    ):
        raise HTTPException(status_code=409, detail="context receipt signature is invalid")
    current = _verified_support(conn, tenant_id=principal.tenant_id, belief_ids=belief_ids)
    current_hashes = [belief.hash_hex for belief in current]
    current_origins = sorted(
        {source_id for belief in current for source_id in belief.origin_source_ids}, key=str
    )
    current_authority = min((belief.authority_rank for belief in current), default=0)
    if (
        len(current) != len(belief_ids)
        or any(belief.status != "active" for belief in current)
        or current_hashes != belief_hashes
        or current_origins != origins
        or current_authority != int(authority_rank)
    ):
        raise HTTPException(status_code=409, detail="context receipt evidence is no longer valid")
    return {
        "belief_ids": belief_ids,
        "belief_hashes": belief_hashes,
        "origin_source_ids": origins,
        "authority_rank": int(authority_rank),
        "expires_at": expires_at,
        "algorithm": algorithm,
        "key_id": key_id,
    }


@app.post("/contexts/receipts", response_model=ContextReceiptOut, status_code=201)
def create_context_receipt(
    body: ContextReceiptIn,
    principal: Principal = Depends(require_roles("writer")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ContextReceiptOut:
    key = validate_key(idempotency_key)
    digest = request_hash(body)
    signer = _control_signer()
    receipt_id = uuid4()
    requested_ids = sorted(set(body.belief_ids), key=str)

    def txn(conn: psycopg.Connection) -> ContextReceiptOut:
        prior = replay(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/contexts/receipts",
            key=key,
            digest=digest,
        )
        if prior is not None:
            return ContextReceiptOut.model_validate(prior)
        if (
            conn.execute(
                "SELECT 1 FROM agents WHERE tenant_id = %s AND agent_id = %s",
                (principal.tenant_id, body.agent_id),
            ).fetchone()
            is None
        ):
            raise HTTPException(status_code=404, detail="unknown agent")
        rows = _verified_support(conn, tenant_id=principal.tenant_id, belief_ids=requested_ids)
        if len(rows) != len(requested_ids):
            raise HTTPException(status_code=422, detail="one or more beliefs are unknown")
        unavailable = [str(row.belief_id) for row in rows if row.status != "active"]
        if unavailable:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "context contains unavailable beliefs",
                    "belief_ids": unavailable,
                },
            )
        belief_ids = [row.belief_id for row in rows]
        belief_hashes = [row.hash_hex for row in rows]
        authority_rank = min(row.authority_rank for row in rows)
        origins = sorted(
            {source_id for row in rows for source_id in row.origin_source_ids}, key=str
        )
        timestamp_row = conn.execute("SELECT now()").fetchone()
        assert timestamp_row is not None
        created_at = timestamp_row[0]
        expires_at = created_at + timedelta(seconds=body.ttl_seconds)
        payload = context_receipt_payload(
            receipt_id=receipt_id,
            tenant_id=principal.tenant_id,
            agent_id=body.agent_id,
            issued_to=principal.principal_id,
            belief_ids=belief_ids,
            belief_hashes=belief_hashes,
            origin_source_ids=origins,
            authority_rank=authority_rank,
            created_at=created_at,
            expires_at=expires_at,
        )
        payload_hash = sha256(payload)
        sig = signer.sign(payload_hash)
        conn.execute(
            "INSERT INTO context_receipts"
            " (receipt_id, tenant_id, agent_id, issued_to, belief_ids, belief_hashes,"
            " origin_source_ids, authority_rank, payload_hash, sig, signer_pubkey,"
            " signing_algorithm, signer_key_id, expires_at, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                receipt_id,
                principal.tenant_id,
                body.agent_id,
                principal.principal_id,
                belief_ids,
                belief_hashes,
                origins,
                authority_rank,
                payload_hash,
                sig,
                signer.public_key_bytes(),
                signer.algorithm,
                signer.key_id,
                expires_at,
                created_at,
            ),
        )
        result = ContextReceiptOut(
            receipt_id=receipt_id,
            agent_id=body.agent_id,
            belief_ids=belief_ids,
            origin_source_ids=origins,
            authority_rank=authority_rank,
            authority_label=label_for_rank(authority_rank),
            expires_at=expires_at,
            sig=sig.hex(),
            signing_algorithm=signer.algorithm,
            signer_key_id=signer.key_id,
        )
        store(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/contexts/receipts",
            key=key,
            digest=digest,
            response_status=201,
            response_body=result.model_dump(mode="json"),
        )
        return result

    return run_tenant_txn(principal.tenant_id, txn)


def _insert_decision(
    conn: psycopg.Connection,
    *,
    principal: Principal,
    signer,
    decision_id: UUID,
    agent_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
    action_digest_value: bytes,
    support_ids: list[UUID],
    context_receipt_id: UUID | None,
    policy: ToolPolicy,
    observed_authority: int,
    verdict: DecisionVerdict,
    reason: str,
    supersedes_decision_id: UUID | None = None,
):
    timestamp_row = conn.execute("SELECT now()").fetchone()
    assert timestamp_row is not None
    created_at = timestamp_row[0]
    payload = decision_payload(
        decision_id=decision_id,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        requested_by=principal.principal_id,
        tool_name=tool_name,
        action_digest_value=action_digest_value,
        support_belief_ids=support_ids,
        context_receipt_id=context_receipt_id,
        risk_class=policy.risk_class,
        required_authority=policy.required_authority,
        observed_authority=observed_authority,
        decision=verdict,
        reason=reason,
        policy_version=policy.policy_version,
        supersedes_decision_id=supersedes_decision_id,
        created_at=created_at,
    )
    sig = signer.sign(sha256(payload))
    conn.execute(
        "INSERT INTO action_decisions"
        " (decision_id, tenant_id, agent_id, requested_by, tool_name, arguments,"
        " action_digest, support_belief_ids, context_receipt_id, supersedes_decision_id,"
        " risk_class, required_authority, observed_authority, decision, reason,"
        " policy_version, sig, signer_pubkey, signing_algorithm, signer_key_id, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s, %s, %s)",
        (
            decision_id,
            principal.tenant_id,
            agent_id,
            principal.principal_id,
            tool_name,
            Json(arguments),
            action_digest_value,
            support_ids,
            context_receipt_id,
            supersedes_decision_id,
            policy.risk_class,
            policy.required_authority,
            observed_authority,
            verdict,
            reason,
            policy.policy_version,
            sig,
            signer.public_key_bytes(),
            signer.algorithm,
            signer.key_id,
            created_at,
        ),
    )
    conn.execute(
        "INSERT INTO memory_events (tenant_id, kind, payload) VALUES (%s, 'action_decision', %s)",
        (
            principal.tenant_id,
            Json(
                {
                    "decision_id": str(decision_id),
                    "agent_id": str(agent_id),
                    "tool_name": tool_name,
                    "decision": verdict,
                    "reason": reason,
                    "support_belief_ids": [str(value) for value in support_ids],
                }
            ),
        ),
    )
    return created_at, sig


def _issue_permit(
    conn: psycopg.Connection,
    *,
    principal: Principal,
    signer,
    decision_id: UUID,
    agent_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
    action_digest_value: bytes,
    support_ids: list[UUID],
    policy_version: str,
    created_at,
):
    permit_id = uuid4()
    nonce = uuid4()
    expires_at = created_at + timedelta(seconds=PERMIT_TTL_SECONDS)
    payload = permit_payload(
        permit_id=permit_id,
        decision_id=decision_id,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        action_digest_value=action_digest_value,
        policy_version=policy_version,
        nonce=nonce,
        expires_at=expires_at,
    )
    signature = signer.sign(sha256(payload))
    token = encode_permit(payload, signature)
    conn.execute(
        "INSERT INTO action_permits"
        " (permit_id, tenant_id, decision_id, token_hash, action_digest, nonce,"
        " signer_pubkey, signing_algorithm, signer_key_id, expires_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            permit_id,
            principal.tenant_id,
            decision_id,
            hashlib.sha256(token.encode()).digest(),
            action_digest_value,
            nonce,
            signer.public_key_bytes(),
            signer.algorithm,
            signer.key_id,
            expires_at,
            created_at,
        ),
    )
    action_id = uuid4()
    conn.execute(
        "INSERT INTO agent_actions"
        " (action_id, tenant_id, agent_id, kind, payload, derived_from, decision_id, permit_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            action_id,
            principal.tenant_id,
            agent_id,
            tool_name,
            Json({"tool_name": tool_name, "arguments": arguments}),
            support_ids,
            decision_id,
            permit_id,
        ),
    )
    return token, permit_id, expires_at, action_id


def _decision_out(
    *,
    decision_id: UUID,
    agent_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
    digest: bytes,
    support_ids: list[UUID],
    policy: ToolPolicy,
    observed_authority: int,
    verdict: DecisionVerdict,
    reason: str,
    created_at,
    sig: bytes,
    signer,
    supersedes_decision_id: UUID | None = None,
    permit: str | None = None,
    permit_id: UUID | None = None,
    permit_expires_at=None,
) -> DecisionOut:
    return DecisionOut(
        decision_id=decision_id,
        agent_id=agent_id,
        tool_name=tool_name,
        arguments=arguments,
        action_digest=digest.hex(),
        support_belief_ids=support_ids,
        risk_class=policy.risk_class,
        required_authority=policy.required_authority,
        required_authority_label=label_for_rank(policy.required_authority),
        observed_authority=observed_authority,
        observed_authority_label=label_for_rank(observed_authority),
        decision=verdict,
        reason=reason,
        policy_version=policy.policy_version,
        created_at=created_at,
        supersedes_decision_id=supersedes_decision_id,
        permit=permit,
        permit_id=permit_id,
        permit_expires_at=permit_expires_at,
        sig=sig.hex(),
        signing_algorithm=signer.algorithm,
        signer_key_id=signer.key_id,
    )


@app.post("/actions/authorize", response_model=DecisionOut, status_code=201)
def authorize_action(
    body: AuthorizeIn,
    principal: Principal = Depends(require_roles("writer")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DecisionOut:
    key = validate_key(idempotency_key)
    request_digest = request_hash(body)
    signer = _control_signer()
    decision_id = uuid4()

    def txn(conn: psycopg.Connection) -> DecisionOut:
        prior = replay(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/actions/authorize",
            key=key,
            digest=request_digest,
        )
        if prior is not None:
            return DecisionOut.model_validate(prior)
        if (
            conn.execute(
                "SELECT 1 FROM agents WHERE tenant_id = %s AND agent_id = %s",
                (principal.tenant_id, body.agent_id),
            ).fetchone()
            is None
        ):
            raise HTTPException(status_code=404, detail="unknown agent")

        policy = resolve_policy(conn, principal.tenant_id, body.tool_name, body.annotations)
        explicit_support = sorted(set(body.support_belief_ids), key=str)
        support_ids = explicit_support
        if body.context_receipt_id is not None:
            receipt = _load_context_receipt(
                conn,
                principal=principal,
                receipt_id=body.context_receipt_id,
                agent_id=body.agent_id,
                trusted_signer=signer,
                expected_issued_to=principal.principal_id,
            )
            receipt_ids = sorted(set(receipt["belief_ids"]), key=str)
            if explicit_support and explicit_support != receipt_ids:
                raise HTTPException(
                    status_code=422,
                    detail="support beliefs must exactly match the signed context receipt",
                )
            support_ids = receipt_ids

        rows: list[VerifiedBelief] = []
        if support_ids:
            rows = _verified_support(conn, tenant_id=principal.tenant_id, belief_ids=support_ids)
            if len(rows) != len(support_ids):
                raise HTTPException(
                    status_code=422, detail="one or more support beliefs are unknown"
                )
        observed_authority = min((row.authority_rank for row in rows), default=0)
        unavailable = [str(row.belief_id) for row in rows if row.status != "active"]

        verdict: DecisionVerdict
        if unavailable:
            verdict = "deny"
            reason = "support includes quarantined or unavailable memory"
        elif (
            auth_required()
            and policy.risk_class in {"navigate", "effect", "purchase", "credential"}
            and body.context_receipt_id is None
        ):
            verdict = "deny"
            reason = "a signed context receipt is required for this action class"
        elif not support_ids:
            verdict = "confirm" if policy.confirmation_allowed else "deny"
            reason = "the action has no memory evidence"
        elif observed_authority >= policy.required_authority:
            verdict = "allow"
            reason = "memory evidence satisfies the registered authority policy"
        elif policy.confirmation_allowed:
            verdict = "confirm"
            reason = "memory authority is below policy; independent confirmation is required"
        else:
            verdict = "deny"
            reason = "memory authority is below policy"

        digest = action_digest(
            tenant_id=principal.tenant_id,
            agent_id=body.agent_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
            support_belief_ids=support_ids,
        )
        created_at, sig = _insert_decision(
            conn,
            principal=principal,
            signer=signer,
            decision_id=decision_id,
            agent_id=body.agent_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
            action_digest_value=digest,
            support_ids=support_ids,
            context_receipt_id=body.context_receipt_id,
            policy=policy,
            observed_authority=observed_authority,
            verdict=verdict,
            reason=reason,
        )
        permit = permit_id = permit_expires_at = None
        if verdict == "allow":
            permit, permit_id, permit_expires_at, _ = _issue_permit(
                conn,
                principal=principal,
                signer=signer,
                decision_id=decision_id,
                agent_id=body.agent_id,
                tool_name=body.tool_name,
                arguments=body.arguments,
                action_digest_value=digest,
                support_ids=support_ids,
                policy_version=policy.policy_version,
                created_at=created_at,
            )
        result = _decision_out(
            decision_id=decision_id,
            agent_id=body.agent_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
            digest=digest,
            support_ids=support_ids,
            policy=policy,
            observed_authority=observed_authority,
            verdict=verdict,
            reason=reason,
            created_at=created_at,
            sig=sig,
            signer=signer,
            permit=permit,
            permit_id=permit_id,
            permit_expires_at=permit_expires_at,
        )
        store(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path="/actions/authorize",
            key=key,
            digest=request_digest,
            response_status=201,
            response_body=result.model_dump(mode="json"),
        )
        return result

    return run_tenant_txn(principal.tenant_id, txn)


@app.post("/actions/decisions/{decision_id}/confirm", response_model=DecisionOut, status_code=201)
def confirm_action(
    decision_id: UUID,
    body: ConfirmIn,
    principal: Principal = Depends(require_roles("operator")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DecisionOut:
    key = validate_key(idempotency_key)
    request_digest = request_hash({"decision_id": decision_id, **body.model_dump(mode="json")})
    signer = _control_signer()
    allowed_decision_id = uuid4()
    path = f"/actions/decisions/{decision_id}/confirm"

    def txn(conn: psycopg.Connection) -> DecisionOut:
        prior = replay(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path=path,
            key=key,
            digest=request_digest,
        )
        if prior is not None:
            return DecisionOut.model_validate(prior)
        row = conn.execute(
            "SELECT agent_id, requested_by, tool_name, arguments, action_digest,"
            " support_belief_ids, context_receipt_id, risk_class, required_authority,"
            " observed_authority, policy_version, reason, sig, signer_pubkey,"
            " signing_algorithm, signer_key_id, created_at, supersedes_decision_id"
            " FROM action_decisions"
            " WHERE tenant_id = %s AND decision_id = %s AND decision = 'confirm' FOR UPDATE",
            (principal.tenant_id, decision_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="confirmation-required decision not found")
        (
            agent_id,
            requested_by,
            tool_name,
            arguments,
            digest,
            support_ids,
            context_receipt_id,
            risk_class,
            required_authority,
            observed_authority,
            policy_version,
            stored_reason,
            stored_sig,
            stored_pubkey,
            stored_algorithm,
            stored_key_id,
            original_created_at,
            original_supersedes,
        ) = row
        if auth_required() and requested_by is not None and requested_by == principal.principal_id:
            raise HTTPException(
                status_code=403, detail="confirmation must come from another principal"
            )
        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        support_ids = list(support_ids or [])
        stored_digest = bytes(digest)
        expected_digest = action_digest(
            tenant_id=principal.tenant_id,
            agent_id=agent_id,
            tool_name=tool_name,
            arguments=arguments,
            support_belief_ids=support_ids,
        )
        original_payload = decision_payload(
            decision_id=decision_id,
            tenant_id=principal.tenant_id,
            agent_id=agent_id,
            requested_by=requested_by,
            tool_name=tool_name,
            action_digest_value=stored_digest,
            support_belief_ids=support_ids,
            context_receipt_id=context_receipt_id,
            risk_class=risk_class,
            required_authority=int(required_authority),
            observed_authority=int(observed_authority),
            decision="confirm",
            reason=stored_reason,
            policy_version=policy_version,
            supersedes_decision_id=original_supersedes,
            created_at=original_created_at,
        )
        if (
            stored_digest != expected_digest
            or stored_key_id != signer.key_id
            or stored_algorithm != signer.algorithm
            or bytes(stored_pubkey) != signer.public_key_bytes()
            or not verify_signature(
                bytes(stored_pubkey), sha256(original_payload), bytes(stored_sig), stored_algorithm
            )
        ):
            raise HTTPException(status_code=409, detail="original decision attestation is invalid")
        if context_receipt_id is not None:
            receipt = _load_context_receipt(
                conn,
                principal=principal,
                receipt_id=context_receipt_id,
                agent_id=agent_id,
                trusted_signer=signer,
                expected_issued_to=requested_by,
            )
            if sorted(set(receipt["belief_ids"]), key=str) != support_ids:
                raise HTTPException(
                    status_code=409, detail="decision no longer matches its context receipt"
                )
        beliefs = _verified_support(conn, tenant_id=principal.tenant_id, belief_ids=support_ids)
        if len(beliefs) != len(support_ids) or any(belief.status != "active" for belief in beliefs):
            raise HTTPException(status_code=409, detail="support was recanted before confirmation")
        try:
            conn.execute(
                "INSERT INTO action_confirmations"
                " (tenant_id, decision_id, confirmed_by, subject, reason)"
                " VALUES (%s, %s, %s, %s, %s)",
                (
                    principal.tenant_id,
                    decision_id,
                    principal.principal_id,
                    principal.subject,
                    body.reason,
                ),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise HTTPException(status_code=409, detail="decision was already confirmed") from exc

        policy = ToolPolicy(
            tool_name=tool_name,
            risk_class=risk_class,
            required_authority=int(required_authority),
            confirmation_allowed=True,
            policy_version=policy_version,
            source="stored",
        )
        confirmed_authority = max(int(observed_authority), USER_CONFIRMED)
        reason = f"independently confirmed by {principal.subject}: {body.reason}"
        created_at, sig = _insert_decision(
            conn,
            principal=principal,
            signer=signer,
            decision_id=allowed_decision_id,
            agent_id=agent_id,
            tool_name=tool_name,
            arguments=arguments,
            action_digest_value=bytes(digest),
            support_ids=support_ids,
            context_receipt_id=context_receipt_id,
            policy=policy,
            observed_authority=confirmed_authority,
            verdict="allow",
            reason=reason,
            supersedes_decision_id=decision_id,
        )
        permit, permit_id, permit_expires_at, _ = _issue_permit(
            conn,
            principal=principal,
            signer=signer,
            decision_id=allowed_decision_id,
            agent_id=agent_id,
            tool_name=tool_name,
            arguments=arguments,
            action_digest_value=bytes(digest),
            support_ids=support_ids,
            policy_version=policy.policy_version,
            created_at=created_at,
        )
        result = _decision_out(
            decision_id=allowed_decision_id,
            agent_id=agent_id,
            tool_name=tool_name,
            arguments=arguments,
            digest=bytes(digest),
            support_ids=support_ids,
            policy=policy,
            observed_authority=confirmed_authority,
            verdict="allow",
            reason=reason,
            created_at=created_at,
            sig=sig,
            signer=signer,
            supersedes_decision_id=decision_id,
            permit=permit,
            permit_id=permit_id,
            permit_expires_at=permit_expires_at,
        )
        store(
            conn,
            tenant_id=principal.tenant_id,
            principal_key=principal.key,
            method="POST",
            path=path,
            key=key,
            digest=request_digest,
            response_status=201,
            response_body=result.model_dump(mode="json"),
        )
        return result

    return run_tenant_txn(principal.tenant_id, txn)


@app.post("/actions/permits/consume", response_model=ConsumeOut)
def consume_permit(
    body: ConsumeIn,
    principal: Principal = Depends(require_roles("writer")),
) -> ConsumeOut:
    trusted_signer = _control_signer()
    try:
        payload, signature, document = decode_permit(body.permit)
        permit_id = UUID(document["permit_id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    def txn(conn: psycopg.Connection):
        row = conn.execute(
            "SELECT p.decision_id, p.token_hash, p.action_digest, p.nonce, p.signer_pubkey,"
            " p.signing_algorithm, p.signer_key_id, p.expires_at, p.consumed_at, p.revoked_at,"
            " d.agent_id, d.tool_name, d.arguments, d.support_belief_ids, d.policy_version,"
            " a.action_id FROM action_permits p"
            " JOIN action_decisions d ON d.decision_id = p.decision_id AND d.tenant_id = p.tenant_id"
            " JOIN agent_actions a ON a.permit_id = p.permit_id AND a.tenant_id = p.tenant_id"
            " WHERE p.tenant_id = %s AND p.permit_id = %s FOR UPDATE",
            (principal.tenant_id, permit_id),
        ).fetchone()
        if row is None:
            return None, "unknown permit"
        (
            decision_id,
            token_hash,
            stored_digest,
            nonce,
            pubkey,
            algorithm,
            signer_key_id,
            expires_at,
            consumed_at,
            revoked_at,
            agent_id,
            tool_name,
            arguments,
            support_ids,
            policy_version,
            action_id,
        ) = row
        if bytes(token_hash) != hashlib.sha256(body.permit.encode()).digest():
            return None, "permit token does not match the stored permit"
        expected_payload = permit_payload(
            permit_id=permit_id,
            decision_id=decision_id,
            tenant_id=principal.tenant_id,
            agent_id=agent_id,
            action_digest_value=bytes(stored_digest),
            policy_version=policy_version,
            nonce=nonce,
            expires_at=expires_at,
        )
        if (
            signer_key_id != trusted_signer.key_id
            or algorithm != trusted_signer.algorithm
            or bytes(pubkey) != trusted_signer.public_key_bytes()
            or not hmac.compare_digest(payload, expected_payload)
            or not verify_signature(bytes(pubkey), sha256(payload), signature, algorithm)
        ):
            return None, "permit signature is invalid"
        if consumed_at is not None:
            return None, "permit was already consumed"
        if revoked_at is not None:
            return None, "permit was revoked"
        timestamp_row = conn.execute("SELECT now()").fetchone()
        assert timestamp_row is not None
        now = timestamp_row[0]
        if expires_at <= now:
            return None, "permit expired"
        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        support_ids = list(support_ids or [])
        if body.tool_name != tool_name:
            return None, "permit is bound to a different tool"
        supplied_digest = action_digest(
            tenant_id=principal.tenant_id,
            agent_id=agent_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
            support_belief_ids=support_ids,
        )
        if supplied_digest != bytes(stored_digest) or body.arguments != arguments:
            return None, "permit is bound to different action arguments"
        beliefs = _verified_support(conn, tenant_id=principal.tenant_id, belief_ids=support_ids)
        if len(beliefs) != len(support_ids) or any(belief.status != "active" for belief in beliefs):
            conn.execute(
                "UPDATE action_permits SET revoked_at = now(), revoke_reason = 'support_unavailable'"
                " WHERE tenant_id = %s AND permit_id = %s",
                (principal.tenant_id, permit_id),
            )
            conn.execute(
                "UPDATE agent_actions SET status = 'aborted', status_reason = 'support_unavailable',"
                " resolved_at = now() WHERE tenant_id = %s AND action_id = %s AND status = 'pending'",
                (principal.tenant_id, action_id),
            )
            return None, "support was quarantined before execution"
        consumed_at = conn.execute(
            "UPDATE action_permits SET consumed_at = now()"
            " WHERE tenant_id = %s AND permit_id = %s AND consumed_at IS NULL"
            " AND revoked_at IS NULL AND expires_at > now() RETURNING consumed_at",
            (principal.tenant_id, permit_id),
        ).fetchone()
        if consumed_at is None:
            return None, "permit is no longer usable"
        conn.execute(
            "UPDATE agent_actions SET status = 'executed', resolved_at = now()"
            " WHERE tenant_id = %s AND action_id = %s AND status = 'pending'",
            (principal.tenant_id, action_id),
        )
        conn.execute(
            "INSERT INTO memory_events (tenant_id, kind, payload) VALUES (%s, 'permit_consumed', %s)",
            (
                principal.tenant_id,
                Json(
                    {
                        "permit_id": str(permit_id),
                        "decision_id": str(decision_id),
                        "action_id": str(action_id),
                        "tool_name": tool_name,
                    }
                ),
            ),
        )
        return ConsumeOut(
            permit_id=permit_id,
            decision_id=decision_id,
            action_id=action_id,
            consumed_at=consumed_at[0],
        ), None

    result, error = run_tenant_txn(principal.tenant_id, txn)
    if error:
        raise HTTPException(status_code=409, detail=error)
    return result


def _row_to_decision(row) -> DecisionOut:
    arguments = json.loads(row[3]) if isinstance(row[3], str) else row[3]
    return DecisionOut(
        decision_id=row[0],
        agent_id=row[1],
        tool_name=row[2],
        arguments=arguments,
        action_digest=bytes(row[4]).hex(),
        support_belief_ids=list(row[5] or []),
        risk_class=row[6],
        required_authority=int(row[7]),
        required_authority_label=label_for_rank(int(row[7])),
        observed_authority=int(row[8]),
        observed_authority_label=label_for_rank(int(row[8])),
        decision=row[9],
        reason=row[10],
        policy_version=row[11],
        created_at=row[12],
        supersedes_decision_id=row[13],
        sig=bytes(row[14]).hex(),
        signing_algorithm=row[15],
        signer_key_id=row[16],
    )


_DECISION_SELECT = (
    "SELECT decision_id, agent_id, tool_name, arguments, action_digest, support_belief_ids,"
    " risk_class, required_authority, observed_authority, decision, reason, policy_version,"
    " created_at, supersedes_decision_id, sig, signing_algorithm, signer_key_id"
    " FROM action_decisions"
)


@app.get("/actions/decisions/{decision_id}", response_model=DecisionOut)
def get_decision(
    decision_id: UUID,
    principal: Principal = Depends(require_roles("writer", "auditor")),
) -> DecisionOut:
    row = run_tenant_txn(
        principal.tenant_id,
        lambda conn: conn.execute(
            _DECISION_SELECT + " WHERE tenant_id = %s AND decision_id = %s",
            (principal.tenant_id, decision_id),
        ).fetchone(),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="unknown decision")
    return _row_to_decision(row)


@app.get("/actions/decisions", response_model=list[DecisionOut])
def list_decisions(
    agent_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require_roles("writer", "auditor")),
) -> list[DecisionOut]:
    def txn(conn):
        if agent_id is None:
            return conn.execute(
                _DECISION_SELECT + " WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
                (principal.tenant_id, limit),
            ).fetchall()
        return conn.execute(
            _DECISION_SELECT
            + " WHERE tenant_id = %s AND agent_id = %s ORDER BY created_at DESC LIMIT %s",
            (principal.tenant_id, agent_id, limit),
        ).fetchall()

    return [_row_to_decision(row) for row in run_tenant_txn(principal.tenant_id, txn)]


@app.put("/policies/tools/{tool_name}", response_model=ToolPolicyOut)
def put_tool_policy(
    tool_name: str,
    body: ToolPolicyIn,
    principal: Principal = Depends(require_roles("policy_admin")),
) -> ToolPolicyOut:
    if not tool_name or len(tool_name) > 256:
        raise HTTPException(status_code=422, detail="tool name must be 1 to 256 characters")

    def txn(conn):
        conn.execute(
            "INSERT INTO tool_policies"
            " (tenant_id, tool_name, risk_class, required_authority, confirmation_allowed,"
            " policy_version, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (tenant_id, tool_name) DO UPDATE SET"
            " risk_class = excluded.risk_class, required_authority = excluded.required_authority,"
            " confirmation_allowed = excluded.confirmation_allowed,"
            " policy_version = excluded.policy_version, updated_by = excluded.updated_by,"
            " updated_at = now()",
            (
                principal.tenant_id,
                tool_name,
                body.risk_class,
                body.required_authority,
                body.confirmation_allowed,
                body.policy_version,
                principal.principal_id,
            ),
        )

    run_tenant_txn(principal.tenant_id, txn)
    return ToolPolicyOut(tool_name=tool_name, source="stored", **body.model_dump())


@app.get("/policies/tools/{tool_name}", response_model=ToolPolicyOut)
def get_tool_policy(
    tool_name: str,
    principal: Principal = Depends(require_roles("writer", "auditor", "policy_admin")),
) -> ToolPolicyOut:
    policy = run_tenant_txn(
        principal.tenant_id,
        lambda conn: resolve_policy(conn, principal.tenant_id, tool_name),
    )
    return ToolPolicyOut(
        tool_name=tool_name,
        risk_class=policy.risk_class,
        required_authority=policy.required_authority,
        confirmation_allowed=policy.confirmation_allowed,
        policy_version=policy.policy_version,
        source=policy.source,
    )


@app.post("/semantic-relations/verify", response_model=RelationVerifyOut)
def verify_semantic_relation(
    body: RelationVerifyIn,
    principal: Principal = Depends(require_roles("operator", "policy_admin")),
) -> RelationVerifyOut:
    if body.left_belief_id == body.right_belief_id:
        raise HTTPException(status_code=422, detail="two distinct beliefs are required")

    def read(conn):
        rows = conn.execute(
            "SELECT belief_id, content FROM beliefs WHERE tenant_id = %s AND belief_id = ANY(%s)",
            (principal.tenant_id, [body.left_belief_id, body.right_belief_id]),
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    beliefs = run_tenant_txn(principal.tenant_id, read)
    if len(beliefs) != 2:
        raise HTTPException(status_code=404, detail="one or more beliefs are unknown")
    try:
        verifier = select_claim_verifier()
        relation = verifier.verify(beliefs[body.left_belief_id], beliefs[body.right_belief_id])
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"claim verifier failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="claim verifier unavailable") from exc

    def write(conn):
        conn.execute(
            "UPSERT INTO semantic_relations"
            " (tenant_id, left_belief_id, right_belief_id, relation, confidence,"
            " evidence_method, evidence_model, evidence_version)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                principal.tenant_id,
                body.left_belief_id,
                body.right_belief_id,
                relation.relation,
                relation.confidence,
                relation.method,
                relation.model,
                relation.version,
            ),
        )

    run_tenant_txn(principal.tenant_id, write)
    return RelationVerifyOut(
        left_belief_id=body.left_belief_id,
        right_belief_id=body.right_belief_id,
        relation=relation.relation,
        confidence=relation.confidence,
        evidence_method=relation.method,
        evidence_model=relation.model,
        evidence_version=relation.version,
    )

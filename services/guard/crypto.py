"""Canonical signed payloads used by receipts, decisions, and permits."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from services.common.attestation import b64url, b64url_decode, canonical_json, sha256


def context_receipt_payload(
    *,
    receipt_id: UUID,
    tenant_id: UUID,
    agent_id: UUID,
    issued_to: UUID | None,
    belief_ids: list[UUID],
    belief_hashes: list[str],
    origin_source_ids: list[UUID],
    authority_rank: int,
    created_at: datetime,
    expires_at: datetime,
) -> bytes:
    return canonical_json(
        {
            "type": "recant.context-receipt.v1",
            "receipt_id": receipt_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "issued_to": issued_to,
            "belief_ids": sorted(str(value) for value in belief_ids),
            "belief_hashes": belief_hashes,
            "origin_source_ids": sorted(str(value) for value in origin_source_ids),
            "authority_rank": authority_rank,
            "created_at": created_at,
            "expires_at": expires_at,
        }
    )


def action_digest(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
    support_belief_ids: list[UUID],
) -> bytes:
    return sha256(
        canonical_json(
            {
                "type": "recant.action.v1",
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "support_belief_ids": sorted(str(value) for value in support_belief_ids),
            }
        )
    )


def decision_payload(
    *,
    decision_id: UUID,
    tenant_id: UUID,
    agent_id: UUID,
    requested_by: UUID | None,
    tool_name: str,
    action_digest_value: bytes,
    support_belief_ids: list[UUID],
    context_receipt_id: UUID | None,
    risk_class: str,
    required_authority: int,
    observed_authority: int,
    decision: str,
    reason: str,
    policy_version: str,
    supersedes_decision_id: UUID | None,
    created_at: datetime,
) -> bytes:
    return canonical_json(
        {
            "type": "recant.action-decision.v2",
            "decision_id": decision_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "requested_by": requested_by,
            "tool_name": tool_name,
            "action_digest": action_digest_value.hex(),
            "support_belief_ids": sorted(str(value) for value in support_belief_ids),
            "context_receipt_id": context_receipt_id,
            "risk_class": risk_class,
            "required_authority": required_authority,
            "observed_authority": observed_authority,
            "decision": decision,
            "reason": reason,
            "policy_version": policy_version,
            "supersedes_decision_id": supersedes_decision_id,
            "created_at": created_at,
        }
    )


def permit_payload(
    *,
    permit_id: UUID,
    decision_id: UUID,
    tenant_id: UUID,
    agent_id: UUID,
    action_digest_value: bytes,
    policy_version: str,
    nonce: UUID,
    expires_at: datetime,
) -> bytes:
    return canonical_json(
        {
            "type": "recant.action-permit.v1",
            "permit_id": permit_id,
            "decision_id": decision_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "action_digest": action_digest_value.hex(),
            "policy_version": policy_version,
            "nonce": nonce,
            "expires_at": expires_at,
        }
    )


def encode_permit(payload: bytes, signature: bytes) -> str:
    return f"rct1.{b64url(payload)}.{b64url(signature)}"


def decode_permit(token: str) -> tuple[bytes, bytes, dict]:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "rct1":
        raise ValueError("permit token has an invalid envelope")
    try:
        payload = b64url_decode(parts[1])
        signature = b64url_decode(parts[2])
        document = json.loads(payload)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("permit token is malformed") from exc
    if document.get("type") != "recant.action-permit.v1":
        raise ValueError("permit token has an unsupported type")
    return payload, signature, document

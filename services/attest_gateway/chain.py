"""Per-agent hash chains over attested memory writes.

The canonical payload is deterministic JSON (sorted keys, no whitespace); the chain
hash is SHA-256 over prev_hash || payload. Timestamps must be timezone-aware UTC:
the gateway assigns them and stores the same value in beliefs.created_at, so the
payload can be recomputed from the row alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

GENESIS = b"\x00" * 32


def canonical_payload(
    *,
    agent_id: UUID,
    seq: int,
    content: str,
    source_id: UUID | None,
    parent_ids: list[UUID],
    ts: datetime,
) -> bytes:
    doc = {
        "agent_id": str(agent_id),
        "seq": seq,
        "content": content,
        "source_id": str(source_id) if source_id else None,
        "parent_ids": sorted(str(p) for p in parent_ids),
        "ts": ts.isoformat(),
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def canonical_payload_v2(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    seq: int,
    content: str,
    source_id: UUID | None,
    parent_ids: list[UUID],
    context_receipt_id: UUID | None,
    authority_rank: int,
    origin_source_ids: list[UUID],
    provenance_method: str,
    provenance_version: str,
    ts: datetime,
) -> bytes:
    """Canonical belief payload that cryptographically binds provenance.

    v1 remains available for historical rows. All new writes use v2 so tenant,
    receipt, propagated source origins, and least authority cannot be altered
    without breaking the per-agent chain.
    """
    doc = {
        "type": "recant.belief.v2",
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "seq": seq,
        "content": content,
        "source_id": str(source_id) if source_id else None,
        "parent_ids": sorted(str(p) for p in parent_ids),
        "context_receipt_id": str(context_receipt_id) if context_receipt_id else None,
        "authority_rank": authority_rank,
        "origin_source_ids": sorted(str(value) for value in origin_source_ids),
        "provenance_method": provenance_method,
        "provenance_version": provenance_version,
        "ts": ts.isoformat(),
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def chain_hash(prev_hash: bytes, payload: bytes) -> bytes:
    return hashlib.sha256(prev_hash + payload).digest()


@dataclass
class ChainRecord:
    agent_id: UUID
    seq: int
    content: str
    source_id: UUID | None
    parent_ids: list[UUID]
    ts: datetime
    prev_hash: bytes
    hash: bytes
    tenant_id: UUID | None = None
    context_receipt_id: UUID | None = None
    authority_rank: int = 0
    origin_source_ids: list[UUID] | None = None
    provenance_method: str = "legacy"
    provenance_version: str = "v1"
    attestation_version: str = "v1"


def record_payload(record: ChainRecord) -> bytes:
    if record.attestation_version == "v1":
        return canonical_payload(
            agent_id=record.agent_id,
            seq=record.seq,
            content=record.content,
            source_id=record.source_id,
            parent_ids=record.parent_ids,
            ts=record.ts,
        )
    if record.attestation_version == "v2" and record.tenant_id is not None:
        return canonical_payload_v2(
            tenant_id=record.tenant_id,
            agent_id=record.agent_id,
            seq=record.seq,
            content=record.content,
            source_id=record.source_id,
            parent_ids=record.parent_ids,
            context_receipt_id=record.context_receipt_id,
            authority_rank=record.authority_rank,
            origin_source_ids=record.origin_source_ids or [],
            provenance_method=record.provenance_method,
            provenance_version=record.provenance_version,
            ts=record.ts,
        )
    raise ValueError(f"unsupported or incomplete attestation version: {record.attestation_version}")


def verify_chain(records: list[ChainRecord]) -> tuple[bool, int]:
    """records must be ordered by seq ascending; returns (valid, first_bad_index).

    first_bad_index is -1 when the chain is valid.
    """
    prev = GENESIS
    for i, r in enumerate(records):
        # prev_hash is persisted as evidence and returned by the APIs. Checking
        # only the recomputed chain would let that stored link be corrupted
        # while verification still reported the record as valid.
        if r.prev_hash != prev:
            return False, i
        try:
            payload = record_payload(r)
        except ValueError:
            return False, i
        if chain_hash(prev, payload) != r.hash:
            return False, i
        prev = r.hash
    return True, -1

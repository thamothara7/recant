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
    hash: bytes


def verify_chain(records: list[ChainRecord]) -> tuple[bool, int]:
    """records must be ordered by seq ascending; returns (valid, first_bad_index).

    first_bad_index is -1 when the chain is valid.
    """
    prev = GENESIS
    for i, r in enumerate(records):
        payload = canonical_payload(
            agent_id=r.agent_id,
            seq=r.seq,
            content=r.content,
            source_id=r.source_id,
            parent_ids=r.parent_ids,
            ts=r.ts,
        )
        if chain_hash(prev, payload) != r.hash:
            return False, i
        prev = r.hash
    return True, -1

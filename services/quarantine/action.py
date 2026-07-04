"""Quarantines are themselves attested (spec section 6).

The action signature is Ed25519 over SHA-256 of a canonical JSON payload, using
the same encoding discipline as the belief chain (sorted keys, no whitespace,
sorted ID lists). Every signed field is persisted durably on the action/incident
rows (quarantine_actions.newly_flipped_ids + incidents.source_id/created_at), so
the signature is recomputable from the stored rows alone by a forensics verifier
that never saw the HTTP response or the outbox event.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID


def canonical_action_payload(
    *,
    incident_id: UUID,
    source_id: UUID,
    newly_flipped_ids: list[UUID],
    belief_count: int,
    actor: str,
    ts: datetime,
) -> bytes:
    doc = {
        "incident_id": str(incident_id),
        "source_id": str(source_id),
        "newly_flipped_ids": sorted(str(b) for b in newly_flipped_ids),
        "belief_count": belief_count,
        "actor": actor,
        "ts": ts.isoformat(),
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def action_digest(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()

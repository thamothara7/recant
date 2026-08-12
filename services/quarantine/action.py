"""Quarantines are themselves attested (spec section 6).

The action signature is over SHA-256 of a canonical JSON payload, using
deterministic Ed25519 locally and AWS KMS ECDSA in production. Every signed
field is persisted durably on the action and incident rows, so a forensics
verifier can reconstruct it without the HTTP response or outbox event. V2 also
binds the tenant and payload type while v1 remains available for old rows.
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
    tenant_id: UUID | None = None,
    attestation_version: str = "v1",
) -> bytes:
    doc: dict[str, object] = {
        "incident_id": str(incident_id),
        "source_id": str(source_id),
        "newly_flipped_ids": sorted(str(b) for b in newly_flipped_ids),
        "belief_count": belief_count,
        "actor": actor,
        "ts": ts.isoformat(),
    }
    if attestation_version == "v2" and tenant_id is not None:
        doc.update(
            {
                "type": "recant.quarantine-action.v2",
                "tenant_id": str(tenant_id),
            }
        )
    elif attestation_version != "v1":
        raise ValueError(f"unsupported or incomplete attestation version: {attestation_version}")
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def action_digest(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()

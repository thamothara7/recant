"""Canonical quarantine-action payload must be byte-stable: a previously stored
signature stays verifiable only if the encoding never drifts (spec section 6).
This pins the exact bytes so any change to key order, separators, id sorting, or
timestamp format fails loudly instead of silently invalidating old signatures."""

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from services.quarantine.action import action_digest, canonical_action_payload

INCIDENT = UUID("00000000-0000-0000-0000-000000000001")
SOURCE = UUID("00000000-0000-0000-0000-000000000002")
B3 = UUID("00000000-0000-0000-0000-000000000003")
B4 = UUID("00000000-0000-0000-0000-000000000004")
TS = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)

EXPECTED = (
    b'{"actor":"auditor","belief_count":2,'
    b'"incident_id":"00000000-0000-0000-0000-000000000001",'
    b'"newly_flipped_ids":["00000000-0000-0000-0000-000000000003",'
    b'"00000000-0000-0000-0000-000000000004"],'
    b'"source_id":"00000000-0000-0000-0000-000000000002",'
    b'"ts":"2026-07-03T12:00:00+00:00"}'
)


def _payload(ids):
    return canonical_action_payload(
        incident_id=INCIDENT,
        source_id=SOURCE,
        newly_flipped_ids=ids,
        belief_count=2,
        actor="auditor",
        ts=TS,
    )


def test_payload_is_byte_stable():
    assert _payload([B3, B4]) == EXPECTED


def test_id_order_does_not_change_payload():
    # The signed doc sorts the id list, so flip order is irrelevant.
    assert _payload([B4, B3]) == _payload([B3, B4])


def test_digest_is_sha256_of_payload():
    assert action_digest(EXPECTED) == hashlib.sha256(EXPECTED).digest()

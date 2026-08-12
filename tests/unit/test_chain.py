from datetime import datetime, timezone
from uuid import uuid4

from services.attest_gateway import chain

TS = datetime(2026, 7, 2, 12, 0, 0, 123456, tzinfo=timezone.utc)


def _build(agent_id, specs):
    """specs: list of (content, source_id, parent_ids). Returns valid ChainRecords."""
    prev = chain.GENESIS
    records = []
    for i, (content, source_id, parent_ids) in enumerate(specs, start=1):
        payload = chain.canonical_payload(
            agent_id=agent_id,
            seq=i,
            content=content,
            source_id=source_id,
            parent_ids=parent_ids,
            ts=TS,
        )
        h = chain.chain_hash(prev, payload)
        records.append(
            chain.ChainRecord(
                agent_id=agent_id,
                seq=i,
                content=content,
                source_id=source_id,
                parent_ids=parent_ids,
                ts=TS,
                prev_hash=prev,
                hash=h,
            )
        )
        prev = h
    return records


def test_chain_hash_is_deterministic():
    payload = chain.canonical_payload(
        agent_id=uuid4(), seq=1, content="x", source_id=None, parent_ids=[], ts=TS
    )
    assert chain.chain_hash(chain.GENESIS, payload) == chain.chain_hash(chain.GENESIS, payload)
    assert len(chain.chain_hash(chain.GENESIS, payload)) == 32


def test_parent_order_does_not_change_payload():
    a, b, agent = uuid4(), uuid4(), uuid4()
    p1 = chain.canonical_payload(
        agent_id=agent, seq=1, content="x", source_id=None, parent_ids=[a, b], ts=TS
    )
    p2 = chain.canonical_payload(
        agent_id=agent, seq=1, content="x", source_id=None, parent_ids=[b, a], ts=TS
    )
    assert p1 == p2


def test_valid_chain_verifies():
    records = _build(uuid4(), [("one", None, []), ("two", uuid4(), []), ("three", None, [])])
    assert chain.verify_chain(records) == (True, -1)


def test_empty_chain_is_valid():
    assert chain.verify_chain([]) == (True, -1)


def test_tampered_content_is_detected_at_index():
    records = _build(uuid4(), [("one", None, []), ("two", None, []), ("three", None, [])])
    records[1].content = "tampered"
    ok, bad = chain.verify_chain(records)
    assert ok is False and bad == 1


def test_tampered_hash_breaks_rest_of_chain():
    records = _build(uuid4(), [("one", None, []), ("two", None, [])])
    records[0].hash = b"\x01" * 32
    ok, bad = chain.verify_chain(records)
    assert ok is False and bad == 0


def test_tampered_stored_prev_hash_is_detected():
    records = _build(uuid4(), [("one", None, []), ("two", None, [])])
    records[1].prev_hash = b"\xff" * 32
    ok, bad = chain.verify_chain(records)
    assert ok is False and bad == 1


def test_v2_chain_binds_tenant_and_propagated_authority():
    tenant_id, agent_id, source_id = uuid4(), uuid4(), uuid4()
    payload = chain.canonical_payload_v2(
        tenant_id=tenant_id,
        agent_id=agent_id,
        seq=1,
        content="trusted claim",
        source_id=source_id,
        parent_ids=[],
        context_receipt_id=None,
        authority_rank=60,
        origin_source_ids=[source_id],
        provenance_method="source",
        provenance_version="v1",
        ts=TS,
    )
    record = chain.ChainRecord(
        agent_id=agent_id,
        seq=1,
        content="trusted claim",
        source_id=source_id,
        parent_ids=[],
        ts=TS,
        prev_hash=chain.GENESIS,
        hash=chain.chain_hash(chain.GENESIS, payload),
        tenant_id=tenant_id,
        authority_rank=60,
        origin_source_ids=[source_id],
        provenance_method="source",
        attestation_version="v2",
    )
    assert chain.verify_chain([record]) == (True, -1)
    record.authority_rank = 90
    assert chain.verify_chain([record]) == (False, 0)

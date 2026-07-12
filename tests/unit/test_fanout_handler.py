"""parse_event pins the decision-12 contract: valid payloads round-trip,
malformed recant events fail loudly (a producer bug, never fixed up silently),
and foreign kinds pass through as None without error."""

import pytest
from uuid import UUID, uuid4

from fanout.handler import MalformedEvent, parse_event

EVENT = uuid4()
INCIDENT = uuid4()
SOURCE = uuid4()
AGENT_A = uuid4()
AGENT_B = uuid4()
B1, B2, B3 = uuid4(), uuid4(), uuid4()


def payload(**overrides) -> dict:
    base = {
        "source_id": str(SOURCE),
        "actor": "auditor",
        "closure_ids": [str(B1), str(B2), str(B3)],
        "evictions": [
            {"agent_id": str(AGENT_A), "belief_ids": [str(B1), str(B2)]},
            {"agent_id": str(AGENT_B), "belief_ids": [str(B3)]},
        ],
        "inferred_edges": [],
    }
    base.update(overrides)
    return base


def test_valid_payload_round_trips():
    event = parse_event(EVENT, "recant", INCIDENT, payload())
    assert event is not None
    assert event.event_id == EVENT
    assert event.incident_id == INCIDENT
    assert event.source_id == SOURCE
    assert event.actor == "auditor"
    assert [e.agent_id for e in event.evictions] == [AGENT_A, AGENT_B]
    assert event.evictions[0].belief_ids == (B1, B2)
    assert sorted(map(str, event.all_belief_ids)) == sorted(map(str, [B1, B2, B3]))


def test_empty_evictions_is_valid():
    # A repeat recant flips nothing: the event still delivers, evicting zero.
    event = parse_event(EVENT, "recant", INCIDENT, payload(evictions=[]))
    assert event is not None
    assert event.evictions == ()
    assert event.all_belief_ids == []


def test_non_recant_kinds_are_ignored_without_error():
    assert parse_event(EVENT, "eviction", INCIDENT, {"anything": True}) is None
    assert parse_event(EVENT, "future_kind", None, {}) is None


@pytest.mark.parametrize(
    "broken",
    [
        {"actor": "auditor"},  # no source_id, no evictions
        payload(evictions="not-a-list"),
        payload(evictions=[{"agent_id": "not-a-uuid", "belief_ids": []}]),
        payload(evictions=[{"belief_ids": ["missing agent_id"]}]),
        payload(evictions=[{"agent_id": str(AGENT_A), "belief_ids": ["not-a-uuid"]}]),
        payload(actor=""),
        payload(source_id="not-a-uuid"),
    ],
)
def test_malformed_recant_events_raise(broken):
    with pytest.raises(MalformedEvent):
        parse_event(EVENT, "recant", INCIDENT, broken)


def test_recant_without_incident_id_raises():
    with pytest.raises(MalformedEvent):
        parse_event(EVENT, "recant", None, payload())


def test_payload_must_be_an_object():
    with pytest.raises(MalformedEvent):
        parse_event(EVENT, "recant", INCIDENT, ["not", "a", "dict"])

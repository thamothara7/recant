"""The Lambda shim, tested with no AWS: a webhook-sink envelope with N recant
rows produces N parsed events and correctly batched PutEvents calls against an
injected fake client. Deployment is U3; the wire format is pinned now."""

import base64
import json
from uuid import uuid4

import pytest

from fanout.handler import MalformedEvent
from fanout.lambda_entry import PUTEVENTS_BATCH, handler, parse_webhook_envelope

SOURCE = uuid4()
AGENT = uuid4()


def recant_row(event_id=None, incident_id=None, belief_ids=None):
    return {
        "value": {
            "after": {
                "event_id": str(event_id or uuid4()),
                "kind": "recant",
                "incident_id": str(incident_id or uuid4()),
                "payload": {
                    "source_id": str(SOURCE),
                    "actor": "auditor",
                    "evictions": [
                        {"agent_id": str(AGENT), "belief_ids": [str(b) for b in (belief_ids or [uuid4()])]}
                    ],
                },
                "created_at": "2026-07-10T00:00:00Z",
            }
        }
    }


class FakeEvents:
    def __init__(self):
        self.calls = []

    def put_events(self, Entries):
        assert len(Entries) <= PUTEVENTS_BATCH
        self.calls.append(Entries)
        return {"FailedEntryCount": 0}


def envelope(rows):
    return {"payload": rows, "length": len(rows)}


def test_n_rows_produce_n_events():
    events = parse_webhook_envelope(envelope([recant_row() for _ in range(3)]))
    assert len(events) == 3


def test_deletes_and_foreign_kinds_are_skipped():
    rows = [
        recant_row(),
        {"value": {"after": None}},  # delete emission
        {"value": {"after": {"event_id": str(uuid4()), "kind": "eviction", "incident_id": None, "payload": {}}}},
    ]
    events = parse_webhook_envelope(envelope(rows))
    assert len(events) == 1


def test_double_encoded_jsonb_payload_is_decoded():
    row = recant_row()
    row["value"]["after"]["payload"] = json.dumps(row["value"]["after"]["payload"])
    events = parse_webhook_envelope(envelope([row]))
    assert len(events) == 1
    assert events[0].actor == "auditor"


def test_malformed_recant_row_raises_so_the_sink_retries():
    row = recant_row()
    row["value"]["after"]["payload"] = {"actor": "auditor"}  # contract violation
    with pytest.raises(MalformedEvent):
        parse_webhook_envelope(envelope([row]))


def test_handler_batches_putevents_at_the_eventbridge_limit():
    fake = FakeEvents()
    body = json.dumps(envelope([recant_row() for _ in range(23)]))
    result = handler({"body": body}, events_client=fake)
    assert result["statusCode"] == 200
    counts = json.loads(result["body"])
    assert counts == {"events": 23, "put_calls": 3}
    assert [len(c) for c in fake.calls] == [10, 10, 3]
    detail = json.loads(fake.calls[0][0]["Detail"])
    assert detail["actor"] == "auditor"
    assert detail["evictions"][0]["agent_id"] == str(AGENT)


def test_base64_encoded_body_is_decoded():
    # A Function URL delivering the POST as binary base64-encodes the body and
    # sets isBase64Encoded; the handler must decode before parsing.
    fake = FakeEvents()
    raw = json.dumps(envelope([recant_row()]))
    event = {"body": base64.b64encode(raw.encode()).decode(), "isBase64Encoded": True}
    result = handler(event, events_client=fake)
    assert json.loads(result["body"]) == {"events": 1, "put_calls": 1}


def test_empty_envelope_makes_no_calls():
    fake = FakeEvents()
    result = handler({"body": json.dumps(envelope([]))}, events_client=fake)
    assert json.loads(result["body"]) == {"events": 0, "put_calls": 0}
    assert fake.calls == []

"""EventBridge consumer against the live cluster: one synthetic EventBridge
event (built by the real receiver code from a real outbox row) applies
exactly once; redelivery no-ops through the fanout_deliveries ledger."""

import json
import time

from tests.integration.conftest import requires_db


def _recant_outbox_event(client, quarantine_client):
    """Seed, recant, and return the recant outbox row as an EventBridge event
    dict shaped exactly the way the receiver would emit it."""
    from fanout.lambda_entry import to_entries
    from fanout.handler import parse_event
    from services.common.db import run_txn

    agent = client.post(
        "/agents", json={"name": f"ebridge-{time.time_ns()}"}
    ).json()
    source = client.post(
        "/sources",
        json={"kind": "web_scrape", "uri": "https://example.com/eb", "trust_tier": "untrusted"},
    ).json()
    r = client.post(
        "/beliefs",
        json={
            "agent_id": agent["agent_id"],
            "content": "eventbridge leg test belief",
            "source_id": source["source_id"],
        },
    )
    assert r.status_code == 201
    recant_r = quarantine_client.post(
        "/recant", json={"source_id": source["source_id"], "actor": "operator"}
    )
    assert recant_r.status_code == 200

    row = run_txn(
        lambda conn: conn.execute(
            "SELECT event_id, kind, incident_id, payload FROM memory_events"
            " WHERE kind = 'recant' AND incident_id = %s",
            (recant_r.json()["incident_id"],),
        ).fetchone()
    )
    event_id, kind, incident_id, payload = row
    payload = json.loads(payload) if isinstance(payload, str) else payload
    event = parse_event(event_id, kind, incident_id, payload)
    (entry,) = to_entries([event], bus_name="recant")
    return {
        "source": entry["Source"],
        "detail-type": entry["DetailType"],
        "detail": json.loads(entry["Detail"]),
    }


@requires_db
class TestEventBridgeConsumer:
    def test_applies_exactly_once(self, client, quarantine_client):
        from fleet.bootstrap import ensure_agent_memory

        ensure_agent_memory()
        from fanout import consumer_entry
        from services.common.db import run_txn

        eb_event = _recant_outbox_event(client, quarantine_client)

        first = consumer_entry.handler(eb_event)
        assert first["duplicate"] is False
        assert first["consumer"] == "cloud-evictor"

        # The delivery ledger has the row and the receipt landed in the outbox.
        event_id = eb_event["detail"]["event_id"]
        ledger = run_txn(
            lambda conn: conn.execute(
                "SELECT consumer, evicted_rows FROM fanout_deliveries WHERE event_id = %s",
                (event_id,),
            ).fetchall()
        )
        assert ("cloud-evictor", first["evicted_rows"]) in ledger

        receipts = run_txn(
            lambda conn: conn.execute(
                "SELECT payload FROM memory_events WHERE kind = 'eviction'"
                " AND incident_id = %s",
                (eb_event["detail"]["incident_id"],),
            ).fetchall()
        )
        payloads = [json.loads(p) if isinstance(p, str) else p for (p,) in receipts]
        assert any(p.get("consumer") == "cloud-evictor" for p in payloads)

        # Redelivery (EventBridge is at-least-once): the ledger makes it a no-op.
        second = consumer_entry.handler(eb_event)
        assert second["duplicate"] is True
        assert second["evicted_rows"] == 0

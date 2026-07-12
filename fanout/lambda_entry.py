"""Lambda entrypoint for the Cloud fanout leg (W3 plan sections 2 and 7).

Written and unit-tested NOW while the webhook envelope format is fresh;
deployment (packaging, IaC under fanout/iac/, function URL) lands with U3.
The body is a transport shim: CockroachDB webhook-sink envelope in, decision-12
events out to EventBridge. All parsing authority lives in fanout/handler.py.

No AWS imports at module scope: boto3 loads lazily and tests inject a fake
client, so the unit suite runs with no AWS SDK or credentials.
"""

from __future__ import annotations

import json
import os
from uuid import UUID

from fanout.handler import MalformedEvent, RecantEvent, parse_event

EVENT_SOURCE = "recant.fanout"
EVENT_DETAIL_TYPE = "recant"
PUTEVENTS_BATCH = 10  # EventBridge PutEvents hard limit per call


def parse_webhook_envelope(body: dict) -> list[RecantEvent]:
    """One webhook-sink POST body -> the recant events it carries.

    The webhook sink wraps rows as {"payload": [{"value": {"after": {row}}},
    ...], "length": N}. Deletes ("after": null) and non-recant kinds are
    skipped; malformed recant rows raise (the sink retries the POST, which is
    the correct pressure for a producer bug).
    """
    events: list[RecantEvent] = []
    for item in body.get("payload", []):
        after = (item.get("value") or {}).get("after")
        if after is None:
            continue
        payload = after.get("payload")
        if isinstance(payload, str):  # webhook sinks may double-encode JSONB
            payload = json.loads(payload)
        event = parse_event(
            UUID(after["event_id"]),
            after["kind"],
            UUID(after["incident_id"]) if after.get("incident_id") else None,
            payload,
        )
        if event is not None:
            events.append(event)
    return events


def to_entries(events: list[RecantEvent], *, bus_name: str) -> list[dict]:
    return [
        {
            "Source": EVENT_SOURCE,
            "DetailType": EVENT_DETAIL_TYPE,
            "EventBusName": bus_name,
            "Detail": json.dumps(
                {
                    "event_id": str(e.event_id),
                    "incident_id": str(e.incident_id),
                    "source_id": str(e.source_id),
                    "actor": e.actor,
                    "evictions": [
                        {"agent_id": str(ev.agent_id), "belief_ids": [str(b) for b in ev.belief_ids]}
                        for ev in e.evictions
                    ],
                }
            ),
        }
        for e in events
    ]


def handler(event: dict, context: object = None, *, events_client=None) -> dict:
    """Lambda Function URL handler: webhook envelope in, PutEvents out.

    events_client is injected by tests; production constructs boto3 lazily.
    Returns 200 with counts on success; a MalformedEvent propagates as 500 so
    the changefeed retries and the lag is visible instead of swallowed.
    """
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):  # Function URLs base64 bodies they read as binary
        import base64

        body = base64.b64decode(body).decode("utf-8")
    if isinstance(body, str):
        body = json.loads(body)

    try:
        events = parse_webhook_envelope(body)
    except MalformedEvent:
        raise

    entries = to_entries(events, bus_name=os.environ.get("RECANT_EVENT_BUS", "recant"))
    if entries and events_client is None:  # pragma: no cover - exercised under U3
        import boto3

        events_client = boto3.client("events")

    put_calls = 0
    for i in range(0, len(entries), PUTEVENTS_BATCH):
        events_client.put_events(Entries=entries[i : i + PUTEVENTS_BATCH])
        put_calls += 1

    return {"statusCode": 200, "body": json.dumps({"events": len(events), "put_calls": put_calls})}

"""Lambda entrypoint for the Cloud fanout leg (W3 plan sections 2 and 7).

Written and unit-tested NOW while the webhook envelope format is fresh;
deployment (packaging, IaC under fanout/iac/, function URL) lands with U3.
The body is a transport shim: CockroachDB webhook-sink envelope in, decision-12
events out to EventBridge. All parsing authority lives in fanout/handler.py.

No AWS imports at module scope: boto3 loads lazily and tests inject a fake
client, so the unit suite runs with no AWS SDK or credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from uuid import UUID

from fanout.handler import MalformedEvent, RecantEvent, parse_event

EVENT_SOURCE = "recant.fanout"
EVENT_DETAIL_TYPE = "recant"
PUTEVENTS_BATCH = 10  # EventBridge PutEvents hard limit per call
MAX_ENTRY_BYTES = int(os.environ.get("RECANT_EVENTBRIDGE_MAX_ENTRY_BYTES", "240000"))


def _authorized(event: dict) -> bool:
    """Verify CockroachDB's configured Basic authorization header by digest."""
    expected = os.environ.get("RECANT_WEBHOOK_AUTH_SHA256")
    if not expected:
        return os.environ.get("RECANT_ENV", "").strip().lower() != "production"
    headers = {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}
    supplied = headers.get("authorization", "")
    return hmac.compare_digest(hashlib.sha256(supplied.encode()).hexdigest(), expected)


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


def to_entries(events: list[RecantEvent], *, bus_name: str, manifest_client=None) -> list[dict]:
    entries: list[dict] = []
    for event in events:
        detail = json.dumps(
            {
                "event_id": str(event.event_id),
                "incident_id": str(event.incident_id),
                "source_id": str(event.source_id),
                "tenant_id": str(event.tenant_id),
                "actor": event.actor,
                "evictions": [
                    {
                        "agent_id": str(eviction.agent_id),
                        "belief_ids": [str(belief_id) for belief_id in eviction.belief_ids],
                    }
                    for eviction in event.evictions
                ],
            }
        )
        if len(detail.encode("utf-8")) > MAX_ENTRY_BYTES:
            bucket = os.environ.get("RECANT_EVENT_MANIFEST_BUCKET")
            if not bucket:
                raise ValueError(
                    f"recant event {event.event_id} is {len(detail.encode('utf-8'))} bytes; "
                    "set RECANT_EVENT_MANIFEST_BUCKET for oversized fanout"
                )
            if manifest_client is None:  # pragma: no cover - exercised against AWS
                import boto3

                manifest_client = boto3.client("s3")
            raw = detail.encode("utf-8")
            digest = hashlib.sha256(raw).hexdigest()
            key = f"fanout/{event.tenant_id}/{event.event_id}.json"
            manifest_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=raw,
                ContentType="application/json",
                ServerSideEncryption="AES256",
            )
            detail = json.dumps(
                {
                    "event_id": str(event.event_id),
                    "manifest": {
                        "bucket": bucket,
                        "key": key,
                        "sha256": digest,
                    },
                }
            )
        entries.append(
            {
                "Source": EVENT_SOURCE,
                "DetailType": EVENT_DETAIL_TYPE,
                "EventBusName": bus_name,
                "Detail": detail,
            }
        )
    return entries


def handler(
    event: dict,
    context: object = None,
    *,
    events_client=None,
    manifest_client=None,
) -> dict:
    """Lambda Function URL handler: webhook envelope in, PutEvents out.

    events_client is injected by tests; production constructs boto3 lazily.
    Returns 200 with counts on success; a MalformedEvent propagates as 500 so
    the changefeed retries and the lag is visible instead of swallowed.
    """
    if not _authorized(event):
        return {
            "statusCode": 401,
            "headers": {"WWW-Authenticate": 'Basic realm="recant-changefeed"'},
            "body": json.dumps({"detail": "invalid webhook authorization"}),
        }
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

    entries = to_entries(
        events,
        bus_name=os.environ.get("RECANT_EVENT_BUS", "recant"),
        manifest_client=manifest_client,
    )
    if entries and events_client is None:  # pragma: no cover - exercised under U3
        import boto3

        events_client = boto3.client("events")

    put_calls = 0
    for i in range(0, len(entries), PUTEVENTS_BATCH):
        batch = entries[i : i + PUTEVENTS_BATCH]
        result = events_client.put_events(Entries=batch)
        put_calls += 1
        # PutEvents reports per-entry failures in an otherwise successful HTTP
        # response. Failing the webhook makes CockroachDB retry the envelope;
        # downstream delivery-ledger idempotency absorbs any repeated successes.
        failed = int(result.get("FailedEntryCount", 0) or 0)
        if failed:
            errors = [
                item.get("ErrorCode", "unknown")
                for item in result.get("Entries", [])
                if item.get("ErrorCode")
            ]
            detail = ", ".join(errors) if errors else "unknown error"
            raise RuntimeError(f"EventBridge rejected {failed} of {len(batch)} entries: {detail}")

    return {"statusCode": 200, "body": json.dumps({"events": len(events), "put_calls": put_calls})}

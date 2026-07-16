"""Lambda entrypoint for the EventBridge delivery leg (W3 plan section 7).

The receiver (fanout/lambda_entry.py) turns changefeed webhook posts into
EventBridge events; this consumer turns one EventBridge event back into a
RecantEvent and applies it with the same fanout/handler.py core the local
worker uses: apply_evictions plus record_delivery in one transaction, so the
effect is exactly-once per consumer under EventBridge's at-least-once
delivery (a duplicate hits the fanout_deliveries primary key and no-ops).

Database URL resolution: DATABASE_URL env wins (local runs and tests); in
Lambda the URL comes from SSM Parameter Store (SecureString named by
RECANT_DB_PARAM), fetched once per warm container. No AWS imports at module
scope; tests inject fakes.
"""

from __future__ import annotations

import os
from uuid import UUID

from fanout.handler import (
    MalformedEvent,
    RecantEvent,
    apply_evictions,
    parse_event,
    record_delivery,
)

DEFAULT_DB_PARAM = "/recant/database_url_cloud"
CONSUMER = os.environ.get("RECANT_CONSUMER", "cloud-evictor")

_cached_url: str | None = None


def detail_to_event(detail: dict) -> RecantEvent:
    """One EventBridge detail (the shape lambda_entry.to_entries emits) back
    into a RecantEvent, revalidated against the decision-12 contract."""
    try:
        event_id = UUID(detail["event_id"])
        incident_id = UUID(detail["incident_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MalformedEvent(f"eventbridge detail missing ids: {exc}") from exc
    payload = {
        "source_id": detail.get("source_id"),
        "actor": detail.get("actor"),
        "evictions": detail.get("evictions"),
    }
    event = parse_event(event_id, "recant", incident_id, payload)
    assert event is not None  # kind is literal 'recant'; parse cannot skip
    return event


def _database_url(*, ssm_client=None) -> str:
    """DATABASE_URL env, else the SSM SecureString, cached per container."""
    global _cached_url
    env = os.environ.get("DATABASE_URL")
    if env:
        return env
    if _cached_url is None:
        if ssm_client is None:  # pragma: no cover - exercised in Lambda
            import boto3

            ssm_client = boto3.client("ssm")
        name = os.environ.get("RECANT_DB_PARAM", DEFAULT_DB_PARAM)
        _cached_url = ssm_client.get_parameter(Name=name, WithDecryption=True)[
            "Parameter"
        ]["Value"]
    return _cached_url


def handler(event: dict, context: object = None, *, conn_factory=None, ssm_client=None) -> dict:
    """EventBridge target: one event in, one exactly-once apply out.

    A MalformedEvent propagates (Lambda error -> EventBridge retry -> DLQ
    pressure), matching the receiver's stance: producer bugs stay visible.
    A duplicate delivery returns duplicate=True and applies nothing.
    """
    import psycopg

    recant_event = detail_to_event(event.get("detail") or {})

    if conn_factory is None:
        url = _database_url(ssm_client=ssm_client)
        conn_factory = lambda: psycopg.connect(url)  # noqa: E731

    with conn_factory() as conn:
        try:
            with conn.transaction():
                receipt = apply_evictions(conn, recant_event, consumer=CONSUMER)
                record_delivery(conn, recant_event.event_id, CONSUMER, receipt)
        except psycopg.errors.UniqueViolation:
            # Redelivery: the ledger row already exists, the transaction rolled
            # back whole, nothing double-applied. This is the ledger working.
            return {
                "event_id": str(recant_event.event_id),
                "consumer": CONSUMER,
                "duplicate": True,
                "evicted_rows": 0,
                "aborted_actions": 0,
            }

    return {
        "event_id": str(recant_event.event_id),
        "consumer": CONSUMER,
        "duplicate": False,
        "evicted_rows": receipt.evicted_rows,
        "aborted_actions": receipt.aborted_actions,
        "apply_ms": receipt.apply_ms,
    }

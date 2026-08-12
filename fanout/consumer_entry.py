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

import hashlib
import json
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
MAX_MANIFEST_BYTES = int(os.environ.get("RECANT_EVENT_MANIFEST_MAX_BYTES", "16777216"))

_cached_url: str | None = None


def _tenant_role_name(tenant_id: UUID) -> str:
    return f"recant_t_{tenant_id.hex}"


def _tenant_roles_enabled() -> bool:
    raw = os.environ.get("RECANT_DB_RLS")
    normalized = raw.strip().lower() if raw is not None else None
    truthy = {"1", "true", "yes", "on"}
    falsey = {"0", "false", "no", "off"}
    if normalized not in {None, *truthy, *falsey}:
        raise RuntimeError("RECANT_DB_RLS must be a boolean value")
    if os.environ.get("RECANT_ENV", "").strip().lower() == "production":
        return True
    return normalized in truthy


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
        "tenant_id": detail.get("tenant_id"),
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
        _cached_url = ssm_client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return _cached_url


def _resolve_manifest(detail: dict, *, s3_client=None) -> dict:
    manifest = detail.get("manifest")
    if not manifest:
        return detail
    try:
        bucket = manifest["bucket"]
        key = manifest["key"]
        expected = manifest["sha256"]
    except (KeyError, TypeError) as exc:
        raise MalformedEvent(f"event manifest is malformed: {exc}") from exc
    allowed = os.environ.get("RECANT_EVENT_MANIFEST_BUCKET")
    if not allowed:
        raise MalformedEvent("RECANT_EVENT_MANIFEST_BUCKET is required for manifest events")
    if bucket != allowed:
        raise MalformedEvent("event manifest points outside the configured bucket")
    if not isinstance(key, str) or not key.startswith("fanout/"):
        raise MalformedEvent("event manifest key is outside the fanout prefix")
    if s3_client is None:  # pragma: no cover - exercised against AWS
        import boto3

        s3_client = boto3.client("s3")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content_length = int(response.get("ContentLength", 0) or 0)
    if content_length > MAX_MANIFEST_BYTES:
        raise MalformedEvent("event manifest exceeds the configured size limit")
    raw = response["Body"].read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise MalformedEvent("event manifest exceeds the configured size limit")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise MalformedEvent("event manifest digest does not match")
    try:
        hydrated = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedEvent("event manifest is not valid JSON") from exc
    if hydrated.get("event_id") != detail.get("event_id"):
        raise MalformedEvent("event manifest id does not match the envelope")
    expected_key = f"fanout/{hydrated.get('tenant_id')}/{hydrated.get('event_id')}.json"
    if key != expected_key:
        raise MalformedEvent("event manifest key does not match its tenant and event")
    return hydrated


def handler(
    event: dict,
    context: object = None,
    *,
    conn_factory=None,
    ssm_client=None,
    s3_client=None,
) -> dict:
    """EventBridge target: one event in, one exactly-once apply out.

    A MalformedEvent propagates (Lambda error -> EventBridge retry -> DLQ
    pressure), matching the receiver's stance: producer bugs stay visible.
    A duplicate delivery returns duplicate=True and applies nothing.
    """
    import psycopg

    detail = _resolve_manifest(event.get("detail") or {}, s3_client=s3_client)
    recant_event = detail_to_event(detail)

    if conn_factory is None:
        url = _database_url(ssm_client=ssm_client)
        conn_factory = lambda: psycopg.connect(url)  # noqa: E731

    with conn_factory() as conn:
        try:
            with conn.transaction():
                if _tenant_roles_enabled():
                    from psycopg import sql

                    conn.execute(
                        sql.SQL("SET LOCAL ROLE {}").format(
                            sql.Identifier(_tenant_role_name(recant_event.tenant_id))
                        )
                    )
                receipt = apply_evictions(conn, recant_event, consumer=CONSUMER)
                record_delivery(
                    conn,
                    recant_event.event_id,
                    CONSUMER,
                    receipt,
                    recant_event.tenant_id,
                )
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

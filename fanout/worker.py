"""Local eviction worker: polls the memory_events outbox (W3 plan section 1).

The poll is an anti-join against fanout_deliveries, never a timestamp cursor:
memory_events stays append-only (W4 audit evidence) and an event committed with
a created_at below an already-advanced cursor can never be skipped. Each event
applies in one serializable transaction together with its delivery row, so the
effect is exactly-once per consumer; a crash between apply and commit rolls the
whole thing back and the next pass redelivers.

The Cloud webhook changefeed replaces only this poll loop (U1+U3); parsing and
applying stay in fanout/handler.py either way.

Usage: python -m fanout.worker --consumer local-evictor [--interval-ms 250] [--once]
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Callable
from uuid import UUID

import psycopg

from fanout.handler import MalformedEvent, apply_evictions, parse_event, record_delivery
from services.common.db import run_txn
from services.common.logging import bind_incident, configure

log = configure("fanout-worker")

DEFAULT_INTERVAL_MS = int(os.environ.get("RECANT_FANOUT_POLL_MS", "250"))
BATCH_LIMIT = 50

# Anti-join poll: recant events this consumer has not delivered yet. Cross-event
# ordering is best-effort (created_at can tie); harmless because evictions are
# idempotent deletes and commute.
POLL_SQL = """
    SELECT e.event_id, e.kind, e.incident_id, e.payload
    FROM memory_events e
    LEFT JOIN fanout_deliveries d
           ON d.event_id = e.event_id AND d.consumer = %s
    WHERE d.event_id IS NULL AND e.kind = 'recant'
    ORDER BY e.created_at
    LIMIT %s
"""

# Test-only seam: called inside the delivery transaction after apply_evictions
# and before record_delivery. The crash-safety test raises here to prove the
# rollback redelivers. Never set outside tests.
_pre_delivery_hook: Callable[[], None] | None = None


def deliver_event(
    event_id: UUID, kind: str, incident_id: UUID | None, payload: dict, *, consumer: str
) -> bool:
    """Apply one outbox event and record its delivery, atomically.

    Returns True if the event was delivered, False if it was skipped
    (malformed: logged loudly and left undelivered so the lag stays visible;
    a malformed recant event is a producer bug, not something to bury).
    """
    try:
        event = parse_event(event_id, kind, incident_id, payload)
    except MalformedEvent as exc:
        log.error("malformed outbox event; leaving undelivered", extra={"fields": {"event_id": str(event_id), "error": str(exc)}})
        return False
    if event is None:  # not ours (the poll filters, but the contract allows any kind)
        return False

    def txn(conn: psycopg.Connection) -> None:
        receipt = apply_evictions(conn, event, consumer=consumer)
        if _pre_delivery_hook is not None:
            _pre_delivery_hook()
        record_delivery(conn, event.event_id, consumer, receipt)
        with bind_incident(str(event.incident_id)):
            log.info(
                "eviction delivered",
                extra={
                    "fields": {
                        "event_id": str(event.event_id),
                        "consumer": consumer,
                        "evicted_rows": receipt.evicted_rows,
                        "aborted_actions": receipt.aborted_actions,
                        "apply_ms": receipt.apply_ms,
                    }
                },
            )

    try:
        run_txn(txn)
    except psycopg.errors.UniqueViolation:
        # Two workers sharing a consumer name raced on this event; the peer's
        # delivery row committed first and this whole transaction rolled back
        # (receipt included), so nothing double-applied. Losing the race is
        # not a crash.
        log.info(
            "event already delivered by a peer worker",
            extra={"fields": {"event_id": str(event.event_id), "consumer": consumer}},
        )
        return False
    return True


def pass_once(consumer: str) -> int:
    """One poll pass: fetch the undelivered batch, deliver each event in its
    own transaction. Returns the number delivered."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(POLL_SQL, (consumer, BATCH_LIMIT)).fetchall()
    delivered = 0
    for event_id, kind, incident_id, payload in rows:
        if deliver_event(event_id, kind, incident_id, payload, consumer=consumer):
            delivered += 1
    return delivered


def main() -> None:
    parser = argparse.ArgumentParser(description="Recant local eviction worker")
    parser.add_argument("--consumer", required=True, help="durable consumer name (delivery ledger key)")
    parser.add_argument("--interval-ms", type=int, default=DEFAULT_INTERVAL_MS)
    parser.add_argument("--once", action="store_true", help="drain the backlog and exit")
    args = parser.parse_args()

    # The worker owns working-memory eviction, so it guarantees the table
    # exists even if no fleet has run yet on this database.
    from fleet.bootstrap import ensure_agent_memory

    ensure_agent_memory()

    log.info("worker started", extra={"fields": {"consumer": args.consumer, "interval_ms": args.interval_ms, "once": args.once}})
    while True:
        delivered = pass_once(args.consumer)
        if args.once:
            if delivered == 0:
                log.info("backlog drained", extra={"fields": {"consumer": args.consumer}})
                return
            continue
        if delivered == 0:
            time.sleep(args.interval_ms / 1000)


if __name__ == "__main__":
    main()

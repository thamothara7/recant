"""Transport-agnostic eviction core (W3 plan section 2).

One handler module, two entrypoints: the local polling worker (fanout/worker.py)
and the Lambda webhook shim (fanout/lambda_entry.py) both parse events with
parse_event and apply them with apply_evictions, so neither transport contains
eviction logic. No AWS imports at module scope.

apply_evictions runs INSIDE the caller's transaction (the compute_closure
pattern): the working-memory deletes, the action aborts, the receipt event, and
the caller's delivery row commit atomically or not at all.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:  # psycopg is annotation-only here: parse_event needs no DB,
    import psycopg  # so the receiver Lambda zip ships without the driver.

AGENT_MEMORY_TABLE = "agent_memory"
DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


class MalformedEvent(ValueError):
    """The event does not satisfy the decision-12 contract."""


@dataclass(frozen=True)
class Eviction:
    agent_id: UUID
    belief_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class RecantEvent:
    event_id: UUID
    incident_id: UUID
    source_id: UUID
    actor: str
    evictions: tuple[Eviction, ...]
    tenant_id: UUID = DEFAULT_TENANT_ID

    @property
    def all_belief_ids(self) -> list[UUID]:
        return [b for e in self.evictions for b in e.belief_ids]


def parse_event(
    event_id: UUID,
    kind: str,
    incident_id: UUID | None,
    payload: dict,
) -> RecantEvent | None:
    """Validate one memory_events row against the decision-12 contract.

    Returns None for kinds other than 'recant' (receipts and future kinds flow
    through the same outbox; consumers ignore what is not theirs). Raises
    MalformedEvent loudly on contract violations: a malformed recant event
    means a producer bug, never something to fix up silently.
    """
    if kind != "recant":
        return None
    if incident_id is None:
        raise MalformedEvent(f"recant event {event_id} has no incident_id")
    if not isinstance(payload, dict):
        raise MalformedEvent(f"recant event {event_id} payload is not an object")

    try:
        source_id = UUID(payload["source_id"])
        tenant_id = UUID(payload.get("tenant_id") or str(DEFAULT_TENANT_ID))
        actor = payload["actor"]
        raw = payload["evictions"]
    except (KeyError, TypeError, ValueError) as exc:
        raise MalformedEvent(f"recant event {event_id} missing contract field: {exc}") from exc
    if not isinstance(actor, str) or not actor:
        raise MalformedEvent(f"recant event {event_id} actor must be a non-empty string")
    if not isinstance(raw, list):
        raise MalformedEvent(f"recant event {event_id} evictions must be a list")

    evictions: list[Eviction] = []
    for i, entry in enumerate(raw):
        try:
            evictions.append(
                Eviction(
                    agent_id=UUID(entry["agent_id"]),
                    belief_ids=tuple(UUID(b) for b in entry["belief_ids"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MalformedEvent(
                f"recant event {event_id} evictions[{i}] malformed: {exc}"
            ) from exc

    return RecantEvent(
        event_id=event_id,
        incident_id=incident_id,
        source_id=source_id,
        actor=actor,
        evictions=tuple(evictions),
        tenant_id=tenant_id,
    )


@dataclass(frozen=True)
class Receipt:
    evicted_rows: int
    aborted_actions: int
    evictions: list[dict]  # [{agent_id, belief_ids, evicted_rows}]
    aborted: list[dict]  # [{action_id, agent_id}]
    apply_ms: int


def apply_evictions(conn: psycopg.Connection, event: RecantEvent, *, consumer: str) -> Receipt:
    """Apply one recant event inside the caller's transaction.

    1. Delete the flipped beliefs from working memory (agent_memory.id IS the
       belief_id, so this is the custody link executing).
    2. Abort pending actions resting on any evicted belief. The array-overlap
       predicate is time-independent: an action enqueued after the recant
       commit but before this pass still aborts.
    3. Write the eviction receipt to the outbox (console ticker + W4
       forensics). The poller filters kind = 'recant', so receipts never
       self-loop.

    The caller records the fanout_deliveries row (record_delivery) in the same
    transaction; a crash anywhere rolls back all of it and the next pass
    redelivers.
    """
    t0 = time.perf_counter()
    belief_ids = event.all_belief_ids

    # EventBridge metadata is not authority. Require an exact match with the
    # append-only tenant outbox row before applying any deletion or abort.
    stored_row = conn.execute(
        "SELECT kind, incident_id, payload FROM memory_events"
        " WHERE tenant_id = %s AND event_id = %s",
        (event.tenant_id, event.event_id),
    ).fetchone()
    if stored_row is None:
        raise MalformedEvent(f"recant event {event.event_id} is not present in the tenant outbox")
    stored_payload = json.loads(stored_row[2]) if isinstance(stored_row[2], str) else stored_row[2]
    stored_event = parse_event(event.event_id, stored_row[0], stored_row[1], stored_payload)
    if stored_event != event:
        raise MalformedEvent(f"recant event {event.event_id} does not match the tenant outbox")

    deleted: list[tuple[UUID, str]] = []
    if belief_ids:
        deleted = conn.execute(
            f"DELETE FROM {AGENT_MEMORY_TABLE} AS memory WHERE id = ANY(%s)"
            " AND EXISTS (SELECT 1 FROM beliefs b WHERE b.tenant_id = %s"
            " AND b.belief_id = memory.id) RETURNING id, agent_id",
            (belief_ids, event.tenant_id),
        ).fetchall()
    deleted_by_agent: dict[str, int] = {}
    for _, agent_ns in deleted:
        deleted_by_agent[agent_ns] = deleted_by_agent.get(agent_ns, 0) + 1

    aborted_rows: list[tuple[UUID, UUID]] = []
    if belief_ids:
        aborted_rows = conn.execute(
            "UPDATE agent_actions SET status = 'aborted', status_reason = 'recant',"
            " incident_id = %s, resolved_at = now()"
            " WHERE tenant_id = %s AND status = 'pending' AND derived_from && %s"
            " RETURNING action_id, agent_id",
            (event.incident_id, event.tenant_id, belief_ids),
        ).fetchall()

    evictions = [
        {
            "agent_id": str(e.agent_id),
            "belief_ids": [str(b) for b in e.belief_ids],
            "evicted_rows": deleted_by_agent.get(str(e.agent_id), 0),
        }
        for e in event.evictions
    ]
    aborted = [
        {"action_id": str(action_id), "agent_id": str(agent_id)}
        for action_id, agent_id in aborted_rows
    ]
    apply_ms = int((time.perf_counter() - t0) * 1000)

    conn.execute(
        "INSERT INTO memory_events (tenant_id, kind, incident_id, payload)"
        " VALUES (%s, 'eviction', %s, %s)",
        (
            event.tenant_id,
            event.incident_id,
            json.dumps(
                {
                    "consumer": consumer,
                    "source_id": str(event.source_id),
                    "apply_ms": apply_ms,
                    "evictions": evictions,
                    "aborted_actions": aborted,
                }
            ),
        ),
    )

    return Receipt(
        evicted_rows=len(deleted),
        aborted_actions=len(aborted_rows),
        evictions=evictions,
        aborted=aborted,
        apply_ms=apply_ms,
    )


def record_delivery(
    conn: psycopg.Connection,
    event_id: UUID,
    consumer: str,
    receipt: Receipt,
    tenant_id: UUID = DEFAULT_TENANT_ID,
) -> None:
    """The durable delivery row; PRIMARY KEY (event_id, consumer) makes a
    duplicate delivery a conflict instead of a silent double-apply."""
    conn.execute(
        "INSERT INTO fanout_deliveries"
        " (tenant_id, event_id, consumer, evicted_rows, aborted_actions)"
        " VALUES (%s, %s, %s, %s, %s)",
        (tenant_id, event_id, consumer, receipt.evicted_rows, receipt.aborted_actions),
    )

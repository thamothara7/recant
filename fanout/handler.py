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
from uuid import UUID

import psycopg

AGENT_MEMORY_TABLE = "agent_memory"


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
            raise MalformedEvent(f"recant event {event_id} evictions[{i}] malformed: {exc}") from exc

    return RecantEvent(
        event_id=event_id,
        incident_id=incident_id,
        source_id=source_id,
        actor=actor,
        evictions=tuple(evictions),
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

    deleted: list[tuple[UUID, str]] = []
    if belief_ids:
        deleted = conn.execute(
            f"DELETE FROM {AGENT_MEMORY_TABLE} WHERE id = ANY(%s) RETURNING id, agent_id",
            (belief_ids,),
        ).fetchall()
    deleted_by_agent: dict[str, int] = {}
    for _, agent_ns in deleted:
        deleted_by_agent[agent_ns] = deleted_by_agent.get(agent_ns, 0) + 1

    aborted_rows: list[tuple[UUID, UUID]] = []
    if belief_ids:
        aborted_rows = conn.execute(
            "UPDATE agent_actions SET status = 'aborted', status_reason = 'recant',"
            " incident_id = %s, resolved_at = now()"
            " WHERE status = 'pending' AND derived_from && %s"
            " RETURNING action_id, agent_id",
            (event.incident_id, belief_ids),
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
        "INSERT INTO memory_events (kind, incident_id, payload) VALUES ('eviction', %s, %s)",
        (
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


def record_delivery(conn: psycopg.Connection, event_id: UUID, consumer: str, receipt: Receipt) -> None:
    """The durable delivery row; PRIMARY KEY (event_id, consumer) makes a
    duplicate delivery a conflict instead of a silent double-apply."""
    conn.execute(
        "INSERT INTO fanout_deliveries (event_id, consumer, evicted_rows, aborted_actions)"
        " VALUES (%s, %s, %s, %s)",
        (event_id, consumer, receipt.evicted_rows, receipt.aborted_actions),
    )

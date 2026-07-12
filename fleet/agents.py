"""Three scripted agents driving the story through the gateway (W3 plan
section 4). Deterministic, no LLM calls: spec section 10 demands a demo that
needs no luck, and Bedrock sits behind U3 regardless. The tick script lives in
fleet/story.py; this module executes it.

The mirror rule (plan section 4): an agent mirrors a belief into working
memory only after the gateway returns 201, and only when the returned status
is active, using str(belief_id) as the document id so a retried mirror is an
upsert. Suspect-born beliefs never enter working memory: the gateway's birth
status closes the write side of post-recant residue, the fleet honoring it
closes the runtime side.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from uuid import UUID

import psycopg
from psycopg.types.json import Json

from fleet import story
from fleet.bootstrap import history_for, store_for
from fleet.gateway import BeliefReceipt, GatewayClient
from services.common.logging import configure

log = configure("fleet")

RETRIEVAL_K = 3


@dataclass
class Fleet:
    gateway: GatewayClient
    agent_ids: dict[str, UUID] = field(default_factory=dict)
    source_ids: dict[str, UUID] = field(default_factory=dict)
    belief_ids: dict[str, UUID] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)
    action_ids: list[UUID] = field(default_factory=list)


def setup(gateway: GatewayClient) -> Fleet:
    """Agents and sources; raises AlreadySeeded on a non-clean database."""
    fleet = Fleet(gateway=gateway)
    for name in story.AGENTS:
        fleet.agent_ids[name] = gateway.create_agent(name)
        history_for(name)  # transcript table + session exist before the first tick
    for key, kind, uri, tier in story.SOURCES:
        fleet.source_ids[key] = gateway.create_source(kind, uri, tier)
    return fleet


def _mirror(fleet: Fleet, agent: str, key: str, receipt: BeliefReceipt, content: str) -> bool:
    if receipt.status != "active":
        log.info(
            "belief born suspect; NOT mirrored into working memory",
            extra={"fields": {"agent": agent, "key": key, "belief_id": str(receipt.belief_id)}},
        )
        return False
    store_for(fleet.agent_ids[agent]).add_texts(
        [content],
        ids=[str(receipt.belief_id)],
        metadatas=[{"story_key": key, "seq": receipt.seq}],
    )
    # Close the mirror-resurrect race: a recant can flip this belief between
    # the gateway 201 and the add_texts above, and its eviction event may have
    # already been delivered, in which case nothing would ever delete this
    # row. Recheck custody AFTER the mirror exists: a flip that committed
    # before the recheck is caught here; a flip that commits after it will be
    # evicted by the worker, because the mirror row now exists to delete.
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        status = conn.execute(
            "SELECT status FROM beliefs WHERE belief_id = %s", (receipt.belief_id,)
        ).fetchone()[0]
        if status != "active":
            conn.execute("DELETE FROM agent_memory WHERE id = %s", (receipt.belief_id,))
            log.warning(
                "belief flipped between write and mirror; mirror removed",
                extra={"fields": {"agent": agent, "key": key, "belief_id": str(receipt.belief_id), "status": status}},
            )
            return False
    return True


def _write_belief(fleet: Fleet, agent: str, key: str) -> None:
    entry = next(b for b in story.BELIEFS if b[0] == key)
    _, _, source_key, content, parent_keys = entry

    # Retrieval before derivation: what the agent's working memory says about
    # the topic it is about to write on. Deterministic (HashEmbedder is token
    # overlap) and it lands in the transcript, so fleet.show can display it.
    retrieved = store_for(fleet.agent_ids[agent]).similarity_search(content, k=RETRIEVAL_K)
    history = history_for(agent)
    if retrieved:
        history.add_user_message(
            f"context for '{key}': " + " | ".join(d.page_content for d in retrieved)
        )

    receipt = fleet.gateway.create_belief(
        fleet.agent_ids[agent],
        content,
        source_id=fleet.source_ids[source_key] if source_key else None,
        parent_ids=[fleet.belief_ids[p] for p in parent_keys],
        embedding=story.EMBEDDINGS[key],
    )
    fleet.belief_ids[key] = receipt.belief_id
    fleet.statuses[key] = receipt.status
    mirrored = _mirror(fleet, agent, key, receipt, content)
    history.add_ai_message(f"wrote belief {key} ({receipt.belief_id}), status {receipt.status}")

    log.info(
        "belief written",
        extra={
            "fields": {
                "agent": agent,
                "key": key,
                "belief_id": str(receipt.belief_id),
                "status": receipt.status,
                "mirrored": mirrored,
                "retrieved": len(retrieved),
            }
        },
    )


def _enqueue_action(fleet: Fleet) -> None:
    spec = story.ACTION
    derived_from = [fleet.belief_ids[k] for k in spec["derived_from_keys"]]
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        action_id = conn.execute(
            "INSERT INTO agent_actions (agent_id, kind, payload, derived_from)"
            " VALUES (%s, %s, %s, %s) RETURNING action_id",
            (
                fleet.agent_ids[spec["agent"]],
                spec["kind"],
                Json(spec["payload"]),
                derived_from,
            ),
        ).fetchone()[0]
    fleet.action_ids.append(action_id)
    history_for(spec["agent"]).add_ai_message(
        f"queued {spec['kind']} action {action_id} for {spec['payload']['customer']}"
    )
    log.info(
        "action enqueued",
        extra={
            "fields": {
                "agent": spec["agent"],
                "action_id": str(action_id),
                "kind": spec["kind"],
                "derived_from": [str(d) for d in derived_from],
            }
        },
    )


def run_ticks(fleet: Fleet, ticks: int) -> None:
    for tick, agent, op, key in story.TICKS:
        if tick > ticks:
            break
        if op in ("ingest", "derive"):
            _write_belief(fleet, agent, key)
        elif op == "enqueue":
            _enqueue_action(fleet)
        else:  # pragma: no cover - the script is a closed set
            raise ValueError(f"unknown tick op {op!r}")

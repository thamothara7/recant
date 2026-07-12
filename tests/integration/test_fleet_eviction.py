"""W3 integration: fleet -> recant -> eviction, end to end on the live cluster
(docs/plans/2026-07-10-week3.md section 6).

The fleet writes the story through the attest gateway (in-process ASGI), the
quarantine service recants the poisoned source, and the fanout worker delivers
the eviction: working-memory rows vanish, the pending ops action aborts, the
receipt and delivery ledger record it, exactly once per consumer.
"""

import os
from uuid import UUID, uuid4

import psycopg
import pytest

from tests.integration.conftest import requires_db

pytestmark = requires_db

THRESHOLD = "0.60"
CONSUMER = "test-evictor"


@pytest.fixture(autouse=True)
def _pin_threshold(monkeypatch):
    monkeypatch.setenv("RECANT_TAINT_THRESHOLD", THRESHOLD)


@pytest.fixture()
def qs(client):  # client fixture (gateway) runs migrations first
    from fastapi.testclient import TestClient

    from services.quarantine.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fleet(client):
    """The full story, written by the fleet through the gateway."""
    from fleet.agents import run_ticks, setup
    from fleet.bootstrap import ensure_agent_memory
    from fleet.gateway import GatewayClient
    from fleet.story import MAX_TICK, check_story

    check_story()
    ensure_agent_memory()
    f = setup(GatewayClient(client))
    run_ticks(f, MAX_TICK)
    return f


def db():
    return psycopg.connect(os.environ["DATABASE_URL"])


def recant(qs, fleet, actor="auditor"):
    r = qs.post("/recant", json={"source_id": str(fleet.source_ids["forum_thread"]), "actor": actor})
    assert r.status_code == 200, r.text
    return r.json()


def memory_ids(conn) -> set[str]:
    return {str(r[0]) for r in conn.execute("SELECT id FROM agent_memory").fetchall()}


# -- bootstrap shape (the go/no-go pin on the package against local v26.2) --


def test_bootstrap_shape_and_vector_plan(fleet):
    from fleet.embeddings import LangChainEmbedder

    with db() as conn:
        cols = {
            name: udt
            for name, udt in conn.execute(
                "SELECT column_name, udt_name FROM information_schema.columns"
                " WHERE table_name = 'agent_memory'"
            ).fetchall()
        }
    # The exact columns the eviction SQL and fleet.show touch, pinned so a
    # package upgrade that moves one fails loudly (plan section 3).
    assert cols == {
        "id": "uuid",
        "agent_id": "text",
        "content": "text",
        "embedding": "vector",
        "metadata": "jsonb",
        "created_at": "timestamptz",
    }

    # A mirrored belief comes back through the package's own search path.
    from fleet.bootstrap import store_for

    docs = store_for(fleet.agent_ids["support"]).similarity_search("extend refunds for a year", k=3)
    assert any("extend refunds up to a year" in d.page_content for d in docs)

    # The namespace-prefixed cosine index serves the package's exact query
    # shape (decision 8: never ship an L2 index under a cosine query).
    emb = LangChainEmbedder().embed_query("refund window")
    emb_txt = "[" + ",".join(str(v) for v in emb) + "]"
    with db() as conn:
        plan = "\n".join(
            r[0]
            for r in conn.execute(
                f"EXPLAIN SELECT id, content, metadata, embedding <=> '{emb_txt}' AS distance"
                f" FROM agent_memory WHERE agent_id = '{fleet.agent_ids['support']}'"
                f" ORDER BY embedding <=> '{emb_txt}' LIMIT 4"
            ).fetchall()
        )
    assert "vector search" in plan, plan


# -- fleet ticks --


def test_fleet_chains_verify_and_mirrors_match_custody(fleet):
    for name, agent_id in fleet.agent_ids.items():
        v = fleet.gateway.verify_chain(agent_id)
        assert v["valid"], f"chain for {name} invalid: {v}"

    with db() as conn:
        rows = conn.execute("SELECT id, agent_id FROM agent_memory").fetchall()
        beliefs = {str(r[0]) for r in conn.execute("SELECT belief_id FROM beliefs").fetchall()}
    # every mirrored row is an attested custody row, namespaced to its agent
    assert rows, "fleet mirrored nothing"
    for mem_id, agent_ns in rows:
        assert str(mem_id) in beliefs
        assert agent_ns in {str(a) for a in fleet.agent_ids.values()}
    # all nine story beliefs were born active and mirrored
    assert len(rows) == len(fleet.belief_ids)


def test_suspect_born_belief_is_not_mirrored(fleet, qs):
    from fleet.agents import _mirror

    recant(qs, fleet)
    # a write arriving after the recant, citing the recanted source: the
    # gateway births it suspect and the fleet must keep it out of working memory
    receipt = fleet.gateway.create_belief(
        fleet.agent_ids["support"],
        "residue: refunds last a year says the forum",
        source_id=fleet.source_ids["forum_thread"],
    )
    assert receipt.status == "suspect"
    mirrored = _mirror(fleet, "support", "residue", receipt, "residue text")
    assert mirrored is False
    with db() as conn:
        assert str(receipt.belief_id) not in memory_ids(conn)


def test_mirror_resurrect_race_is_closed(fleet):
    from fleet.agents import _mirror
    from fleet.gateway import BeliefReceipt

    # A belief the fleet mirrored while active. Simulate a recant flipping it in
    # the window between the gateway's 201 and the mirror write: with the
    # eviction possibly already delivered, only the post-mirror recheck stops
    # this row from surviving as post-recant residue.
    key = "policy_window"
    bid = fleet.belief_ids[key]
    with db() as conn:
        conn.execute("UPDATE beliefs SET status = 'quarantined' WHERE belief_id = %s", (bid,))

    receipt = BeliefReceipt(belief_id=bid, status="active", seq=1)
    mirrored = _mirror(fleet, "researcher", key, receipt, "The standard refund window is 30 days.")
    assert mirrored is False
    with db() as conn:
        assert str(bid) not in memory_ids(conn)


# -- end-to-end eviction --


def test_end_to_end_eviction(fleet, qs):
    from fanout.worker import pass_once

    tainted_ids = {
        str(fleet.belief_ids[k]) for k in ("forum_claim", "support_paraphrase", "ops_action")
    }
    clean_ids = {str(b) for k, b in fleet.belief_ids.items() if str(b) not in tainted_ids}

    body = recant(qs, fleet)
    assert set(map(str, body["newly_flipped_ids"])) == tainted_ids

    delivered = pass_once(CONSUMER)
    assert delivered == 1

    with db() as conn:
        remaining = memory_ids(conn)
        assert tainted_ids.isdisjoint(remaining), "flipped beliefs still in working memory"
        assert clean_ids <= remaining, "eviction touched clean working memory"

        action = conn.execute(
            "SELECT status, status_reason, incident_id, resolved_at FROM agent_actions"
        ).fetchone()
        assert action[0] == "aborted"
        assert action[1] == "recant"
        assert str(action[2]) == str(body["incident_id"])
        assert action[3] is not None

        receipt = conn.execute(
            "SELECT payload FROM memory_events WHERE kind = 'eviction'"
        ).fetchone()[0]
        assert receipt["consumer"] == CONSUMER
        assert receipt["source_id"] == str(fleet.source_ids["forum_thread"])
        per_agent = {e["agent_id"]: e["evicted_rows"] for e in receipt["evictions"]}
        assert per_agent == {
            str(fleet.agent_ids["researcher"]): 1,
            str(fleet.agent_ids["support"]): 1,
            str(fleet.agent_ids["ops"]): 1,
        }
        assert len(receipt["aborted_actions"]) == 1
        assert receipt["aborted_actions"][0]["agent_id"] == str(fleet.agent_ids["ops"])

        delivery = conn.execute(
            "SELECT evicted_rows, aborted_actions FROM fanout_deliveries WHERE consumer = %s",
            (CONSUMER,),
        ).fetchone()
        assert delivery == (3, 1)


def test_exactly_once_and_idempotent_repeat_recant(fleet, qs):
    from fanout.worker import pass_once

    recant(qs, fleet)
    assert pass_once(CONSUMER) == 1
    assert pass_once(CONSUMER) == 0  # nothing new: the anti-join is empty

    # repeat recant flips 0: its event still delivers, evicting and aborting 0
    body2 = recant(qs, fleet)
    assert body2["belief_count"] == 0
    assert pass_once(CONSUMER) == 1
    with db() as conn:
        row = conn.execute(
            "SELECT evicted_rows, aborted_actions FROM fanout_deliveries"
            " WHERE consumer = %s ORDER BY delivered_at DESC LIMIT 1",
            (CONSUMER,),
        ).fetchone()
        assert row == (0, 0)


def test_same_consumer_worker_race_loses_without_crashing(fleet, qs):
    from fanout.worker import deliver_event, pass_once

    recant(qs, fleet)
    assert pass_once(CONSUMER) == 1

    with db() as conn:
        ev = conn.execute(
            "SELECT event_id, kind, incident_id, payload FROM memory_events WHERE kind = 'recant'"
        ).fetchone()

    # A peer worker sharing the consumer name redelivers the same event: the
    # delivery-row PK collides, the whole transaction rolls back, and losing the
    # race is reported (False) rather than crashing the process.
    assert deliver_event(ev[0], ev[1], ev[2], ev[3], consumer=CONSUMER) is False

    with db() as conn:
        # the rolled-back retry added neither a second delivery nor a second receipt
        assert conn.execute(
            "SELECT count(*) FROM fanout_deliveries WHERE consumer = %s", (CONSUMER,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM memory_events WHERE kind = 'eviction'"
        ).fetchone()[0] == 1


def test_crash_between_apply_and_delivery_redelivers(fleet, qs, monkeypatch):
    import fanout.worker as worker

    recant(qs, fleet)

    class Boom(RuntimeError):
        pass

    def explode():
        raise Boom("crash before the delivery row")

    monkeypatch.setattr(worker, "_pre_delivery_hook", explode)
    with pytest.raises(Boom):
        worker.pass_once(CONSUMER)

    with db() as conn:
        # the whole transaction rolled back: memory intact, action pending,
        # no receipt, no delivery
        assert len(memory_ids(conn)) == len(fleet.belief_ids)
        assert conn.execute("SELECT count(*) FROM memory_events WHERE kind='eviction'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM fanout_deliveries").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM agent_actions").fetchone()[0] == "pending"

    monkeypatch.setattr(worker, "_pre_delivery_hook", None)
    assert worker.pass_once(CONSUMER) == 1
    with db() as conn:
        assert conn.execute("SELECT count(*) FROM fanout_deliveries").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM agent_actions").fetchone()[0] == "aborted"


def test_action_enqueued_after_recant_still_aborts(fleet, qs):
    from fanout.worker import pass_once

    body = recant(qs, fleet)
    # the race: a second action lands AFTER the recant commit, before the
    # worker pass; the overlap predicate is time-independent
    with db() as conn:
        late_action = conn.execute(
            "INSERT INTO agent_actions (agent_id, kind, payload, derived_from)"
            " VALUES (%s, 'refund', '{}', %s) RETURNING action_id",
            (fleet.agent_ids["ops"], [fleet.belief_ids["support_paraphrase"]]),
        ).fetchone()[0]

    pass_once(CONSUMER)
    with db() as conn:
        status, reason, incident = conn.execute(
            "SELECT status, status_reason, incident_id FROM agent_actions WHERE action_id = %s",
            (late_action,),
        ).fetchone()
    assert (status, reason, str(incident)) == ("aborted", "recant", str(body["incident_id"]))


def test_demo_visible_eviction_in_show_context(fleet, qs):
    from fanout.worker import pass_once
    from fleet.show import assemble_context

    paraphrase = "extend refunds up to a year"
    before = assemble_context("support", "refund policy window")
    before_texts = [m["content"] for m in before["memory"]]
    assert any(paraphrase in t for t in before_texts)

    recant(qs, fleet)
    pass_once(CONSUMER)

    after = assemble_context("support", "refund policy window")
    after_texts = [m["content"] for m in after["memory"]]
    assert not any(paraphrase in t for t in after_texts), "paraphrase survived eviction"
    # clean working memory is untouched, both times
    for clean in ("support portal", "30 day window"):
        assert any(clean in t for t in before_texts)
        assert any(clean in t for t in after_texts)
    # the transcript is the agent's own record: eviction never edits it
    assert before["transcript"] == after["transcript"]


def test_second_consumer_gets_its_own_delivery(fleet, qs):
    from fanout.worker import pass_once

    recant(qs, fleet)
    assert pass_once("consumer-a") == 1
    assert pass_once("consumer-b") == 1  # its own ledger, same event
    with db() as conn:
        rows = dict(
            conn.execute(
                "SELECT consumer, evicted_rows FROM fanout_deliveries ORDER BY consumer"
            ).fetchall()
        )
    # evictions are idempotent deletes: the first consumer did the work, the
    # second delivered the same event against already-clean memory
    assert rows == {"consumer-a": 3, "consumer-b": 0}


def test_worker_ignores_malformed_event_loudly(fleet, qs):
    from fanout.worker import pass_once

    with db() as conn:
        conn.execute(
            "INSERT INTO memory_events (kind, incident_id, payload)"
            " VALUES ('recant', %s, '{\"broken\": true}')",
            (uuid4(),),
        )
    # FK: incident must exist for the delivery row only; the malformed event
    # is skipped before any write, so a bogus incident id is fine here
    assert pass_once(CONSUMER) == 0
    with db() as conn:
        assert conn.execute("SELECT count(*) FROM fanout_deliveries").fetchone()[0] == 0

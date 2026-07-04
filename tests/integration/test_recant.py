"""Integration tests for the taint engine + quarantine service (W2).

Explicit vectors give exact threshold control: `axis(i)` beliefs are mutually
orthogonal (similarity 0); `mix(i, j, w)` sits between axes with a chosen
cosine. The taint threshold is pinned per-test via RECANT_TAINT_THRESHOLD.
"""

import json
import math
import threading
import time

import pytest

from tests.integration.conftest import requires_db

pytestmark = requires_db

THRESHOLD = "0.60"


@pytest.fixture(autouse=True)
def _pin_threshold(monkeypatch):
    monkeypatch.setenv("RECANT_TAINT_THRESHOLD", THRESHOLD)


@pytest.fixture()
def qs(client):  # client fixture (gateway) runs migrations first
    from fastapi.testclient import TestClient

    from services.quarantine.app import app

    with TestClient(app) as c:
        yield c


DIM = 1024


def axis(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def mix(i: int, j: int, similarity_to_i: float) -> list[float]:
    """Unit vector with cosine `similarity_to_i` to axis(i), remainder on axis(j)."""
    v = [0.0] * DIM
    v[i] = similarity_to_i
    v[j] = math.sqrt(1.0 - similarity_to_i**2)
    return v


class Fixture:
    def __init__(self, client):
        self.client = client
        self.agents = {}
        self.sources = {}

    def agent(self, name: str) -> str:
        r = self.client.post("/agents", json={"name": name})
        assert r.status_code == 201, r.text
        self.agents[name] = r.json()["agent_id"]
        return self.agents[name]

    def source(self, key: str, trust: str = "untrusted") -> str:
        r = self.client.post(
            "/sources",
            json={"kind": "web", "uri": f"https://example.com/{key}", "trust_tier": trust},
        )
        assert r.status_code == 201, r.text
        self.sources[key] = r.json()["source_id"]
        return self.sources[key]

    def belief(self, agent: str, content: str, *, source=None, parents=(), embedding=None) -> dict:
        r = self.client.post(
            "/beliefs",
            json={
                "agent_id": self.agents[agent],
                "content": content,
                "source_id": self.sources.get(source) if source else None,
                "parent_ids": list(parents),
                "embedding": embedding,
            },
        )
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture()
def fx(client):
    f = Fixture(client)
    f.agent("researcher")
    f.agent("support")
    f.agent("ops")
    f.source("forum", "untrusted")
    f.source("vendor", "verified")
    return f


def statuses(ids: list[str]) -> dict[str, str]:
    from services.common.db import get_pool

    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT belief_id, status FROM beliefs WHERE belief_id = ANY(%s::uuid[])", (ids,)
        ).fetchall()
    return {str(b): s for b, s in rows}


def test_explicit_closure_flips_seed_and_descendants(fx, qs):
    poison = fx.belief("researcher", "refund window is 365 days", source="forum")
    child = fx.belief("support", "honor the 365 day window", parents=[poison["belief_id"]])
    grandchild = fx.belief("ops", "approve old refunds", parents=[child["belief_id"]])
    clean = fx.belief("researcher", "standard window is 30 days", source="vendor")

    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["belief_count"] == 3

    st = statuses([poison["belief_id"], child["belief_id"], grandchild["belief_id"], clean["belief_id"]])
    assert st[poison["belief_id"]] == "quarantined"
    assert st[child["belief_id"]] == "quarantined"
    assert st[grandchild["belief_id"]] == "quarantined"
    assert st[clean["belief_id"]] == "active"


def test_implicit_closure_catches_paraphrase_and_materializes_edge(fx, qs):
    poison = fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    paraphrase = fx.belief("support", "reworded claim", embedding=mix(0, 1, 0.9))  # no FK
    unrelated = fx.belief("ops", "different topic", embedding=axis(2))

    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    out = r.json()
    assert r.status_code == 200, r.text
    assert out["belief_count"] == 2

    st = statuses([poison["belief_id"], paraphrase["belief_id"], unrelated["belief_id"]])
    assert st[paraphrase["belief_id"]] == "quarantined"
    assert st[unrelated["belief_id"]] == "active"

    edges = [
        e for e in out["inferred_edges"]
        if e["child_id"] == paraphrase["belief_id"] and e["parent_id"] == poison["belief_id"]
    ]
    assert len(edges) == 1
    assert edges[0]["score"] == pytest.approx(0.9, abs=0.01)

    from services.common.db import get_pool

    with get_pool().connection() as conn:
        kind, score = conn.execute(
            "SELECT kind, score FROM derivations WHERE child_id = %s AND parent_id = %s",
            (paraphrase["belief_id"], poison["belief_id"]),
        ).fetchone()
    assert kind == "inferred"
    assert score == pytest.approx(0.9, abs=0.01)


def test_transitive_closure_through_inferred_member(fx, qs):
    poison = fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    paraphrase = fx.belief("support", "reworded claim", embedding=mix(0, 1, 0.9))
    downstream = fx.belief("ops", "action from paraphrase", parents=[paraphrase["belief_id"]])

    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    assert r.json()["belief_count"] == 3
    assert statuses([downstream["belief_id"]])[downstream["belief_id"]] == "quarantined"


def test_threshold_boundary_excludes_below(fx, qs):
    fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    below = fx.belief("support", "vaguely related", embedding=mix(0, 1, 0.55))  # < 0.60

    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    assert r.json()["belief_count"] == 1
    assert statuses([below["belief_id"]])[below["belief_id"]] == "active"


def test_window_excludes_beliefs_predating_the_source(fx, qs):
    # Written BEFORE the poisoned source exists in the system: cannot be its
    # contamination even at similarity 1.0.
    early = fx.belief("support", "coincidentally similar", embedding=axis(0))
    fx.source("late_forum", "untrusted")
    fx.belief("researcher", "poisoned claim", source="late_forum", embedding=axis(0))

    r = qs.post("/recant", json={"source_id": fx.sources["late_forum"], "actor": "test"})
    assert r.json()["belief_count"] == 1
    assert statuses([early["belief_id"]])[early["belief_id"]] == "active"


def test_unrecorded_paraphrase_between_source_creation_and_first_citation_is_caught(fx, qs):
    # The paraphrase predates the first RECORDED citation but not the source
    # itself: window anchors to sources.created_at (design review 2026-07-03).
    paraphrase = fx.belief("support", "early unrecorded paraphrase", embedding=mix(0, 1, 0.9))
    poison = fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    assert paraphrase["created_at"] < poison["created_at"]

    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    assert r.json()["belief_count"] == 2
    assert statuses([paraphrase["belief_id"]])[paraphrase["belief_id"]] == "quarantined"


def test_adaptive_k_widens_past_near_duplicate_crowd(fx, qs, monkeypatch):
    poison = fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    crowd = [
        fx.belief("support", f"near duplicate {i}", embedding=mix(0, 1, 0.95))
        for i in range(8)
    ]
    farther = fx.belief("ops", "paraphrase past the crowd", embedding=mix(0, 1, 0.70))

    import services.taint_engine.engine as engine_mod

    monkeypatch.setattr(engine_mod, "KNN_TOP_K", 5)
    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    out = r.json()
    assert out["belief_count"] == 1 + len(crowd) + 1, out
    assert statuses([farther["belief_id"]])[farther["belief_id"]] == "quarantined"


def test_round_cap_sets_rounds_capped_and_leaves_closure_incomplete(fx):
    """The 10-round runaway guard: with max_rounds=1 the implicit hit is found
    but its explicit child is never expanded, so rounds_capped is True (distinct
    from kNN truncation) and the closure is knowingly incomplete."""
    from services.taint_engine.engine import compute_closure
    from services.common.db import get_pool

    poison = fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    paraphrase = fx.belief("support", "reworded claim", embedding=mix(0, 1, 0.9))
    child = fx.belief("ops", "explicit child of paraphrase", parents=[paraphrase["belief_id"]])

    with get_pool().connection() as conn:
        c = compute_closure(conn, fx.sources["forum"], threshold=0.60, max_rounds=1)

    members = {str(m) for m in c.member_ids}
    assert c.rounds_capped is True
    assert c.knn_truncated is False
    assert paraphrase["belief_id"] in members
    assert child["belief_id"] not in members  # its round never ran


def test_knn_truncation_sets_knn_truncated_not_rounds_capped(fx):
    """A near-duplicate crowd larger than max_k leaves the kNN boundary hot at the
    cap: knn_truncated is True while rounds_capped stays False."""
    from services.taint_engine.engine import compute_closure
    from services.common.db import get_pool

    fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    for i in range(4):
        fx.belief("support", f"near duplicate {i}", embedding=mix(0, 1, 0.95))

    with get_pool().connection() as conn:
        c = compute_closure(conn, fx.sources["forum"], threshold=0.60, top_k=2, max_k=2)

    assert c.knn_truncated is True
    assert c.rounds_capped is False


def test_idempotent_second_recant_flips_zero_and_audits(fx, qs):
    fx.belief("researcher", "poisoned claim", source="forum")
    first = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"}).json()
    second = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"}).json()

    assert first["belief_count"] == 1
    assert second["belief_count"] == 0
    assert first["incident_id"] != second["incident_id"]

    from services.common.db import get_pool

    with get_pool().connection() as conn:
        incidents = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
        actions = conn.execute("SELECT count(*) FROM quarantine_actions").fetchone()[0]
    assert incidents == 2
    assert actions == 2


def test_retracted_beliefs_are_not_resurrected(fx, qs):
    poison = fx.belief("researcher", "poisoned claim", source="forum")

    from services.common.db import get_pool

    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE beliefs SET status = 'retracted' WHERE belief_id = %s",
            (poison["belief_id"],),
        )

    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    assert r.json()["belief_count"] == 0
    assert statuses([poison["belief_id"]])[poison["belief_id"]] == "retracted"


def test_recant_action_is_attested(fx, qs):
    """A forensics verifier reconstructs the signed payload from the STORED rows
    alone (no HTTP response, no outbox event) and checks the signature."""
    from services.attest_gateway.signer import dev_action_signer_for, verify_signature
    from services.common.db import get_pool
    from services.quarantine.action import action_digest, canonical_action_payload

    fx.belief("researcher", "poisoned claim", source="forum")
    out = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "auditor"}).json()

    with get_pool().connection() as conn:
        belief_count, actor, sig, flipped, source_id, incident_created = conn.execute(
            "SELECT qa.belief_count, qa.actor, qa.sig, qa.newly_flipped_ids,"
            " i.source_id, i.created_at"
            " FROM quarantine_actions qa JOIN incidents i USING (incident_id)"
            " WHERE qa.incident_id = %s",
            (out["incident_id"],),
        ).fetchone()

    payload = canonical_action_payload(
        incident_id=out["incident_id"],
        source_id=source_id,
        newly_flipped_ids=flipped,
        belief_count=belief_count,
        actor=actor,
        ts=incident_created,
    )
    pubkey = dev_action_signer_for(actor).public_key_bytes()
    assert verify_signature(pubkey, action_digest(payload), bytes(sig))


def test_action_signature_is_domain_separated_from_agent_keys(fx, qs):
    """An action signed for actor='researcher' must NOT verify under the
    researcher AGENT's belief-chain pubkey: the keyspaces are disjoint, so a
    quarantine action can never be mistaken for an act the agent authorized."""
    from services.attest_gateway.signer import dev_signer_for, verify_signature
    from services.common.db import get_pool
    from services.quarantine.action import action_digest, canonical_action_payload

    fx.belief("researcher", "poisoned claim", source="forum")
    out = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "researcher"}).json()

    with get_pool().connection() as conn:
        belief_count, sig, flipped, source_id, incident_created = conn.execute(
            "SELECT qa.belief_count, qa.sig, qa.newly_flipped_ids, i.source_id, i.created_at"
            " FROM quarantine_actions qa JOIN incidents i USING (incident_id)"
            " WHERE qa.incident_id = %s",
            (out["incident_id"],),
        ).fetchone()

    payload = canonical_action_payload(
        incident_id=out["incident_id"],
        source_id=source_id,
        newly_flipped_ids=flipped,
        belief_count=belief_count,
        actor="researcher",
        ts=incident_created,
    )
    agent_pubkey = dev_signer_for("researcher").public_key_bytes()
    assert not verify_signature(agent_pubkey, action_digest(payload), bytes(sig))


def test_outbox_event_carries_eviction_contract(fx, qs):
    poison = fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    paraphrase = fx.belief("support", "reworded claim", embedding=mix(0, 1, 0.9))
    out = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"}).json()

    from services.common.db import get_pool

    with get_pool().connection() as conn:
        kind, incident_id, payload = conn.execute(
            "SELECT kind, incident_id, payload FROM memory_events"
        ).fetchone()
    assert kind == "recant"
    assert str(incident_id) == out["incident_id"]
    payload = payload if isinstance(payload, dict) else json.loads(payload)
    assert sorted(payload["closure_ids"]) == sorted([poison["belief_id"], paraphrase["belief_id"]])
    evicted = {e["agent_id"]: e["belief_ids"] for e in payload["evictions"]}
    assert evicted[fx.agents["researcher"]] == [poison["belief_id"]]
    assert evicted[fx.agents["support"]] == [paraphrase["belief_id"]]


def test_suspect_producer_on_write_path(fx, qs):
    poison = fx.belief("researcher", "poisoned claim", source="forum")
    qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})

    residue_child = fx.belief("support", "derived after recant", parents=[poison["belief_id"]])
    residue_cite = fx.belief("ops", "cites recanted source", source="forum")
    clean = fx.belief("ops", "cites clean source", source="vendor")

    assert residue_child["status"] == "suspect"
    assert residue_cite["status"] == "suspect"
    assert clean["status"] == "active"

    # And a later recant sweeps the suspect residue into quarantine.
    again = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"}).json()
    assert residue_cite["belief_id"] in again["newly_flipped_ids"]
    assert residue_child["belief_id"] in again["newly_flipped_ids"]


def test_preview_is_read_only(fx, qs):
    poison = fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    fx.belief("support", "reworded claim", embedding=mix(0, 1, 0.9))

    r = qs.post("/taint/preview", json={"source_id": fx.sources["forum"]})
    assert r.status_code == 200
    assert r.json()["would_flip"] == 2

    from services.common.db import get_pool

    with get_pool().connection() as conn:
        assert conn.execute("SELECT count(*) FROM incidents").fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM derivations WHERE kind = 'inferred'"
        ).fetchone()[0] == 0
    assert statuses([poison["belief_id"]])[poison["belief_id"]] == "active"


def test_unknown_source_404(qs):
    r = qs.post("/recant", json={"source_id": "00000000-0000-0000-0000-000000000000", "actor": "t"})
    assert r.status_code == 404


def test_judge_overlay_headers(fx, qs):
    fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    values = r.headers.get_list("X-Recant-Primitive")
    assert any(v.startswith("SERIALIZABLE TXN | ") for v in values)
    assert any(v.startswith("VECTOR kNN | ") for v in values)


def test_knn_query_uses_vector_index(fx, qs):
    """The judge overlay must never claim an index-backed kNN that is a scan."""
    from services.common.db import get_pool
    from services.common.vectors import to_vector_literal

    fx.belief("researcher", "poisoned claim", source="forum", embedding=axis(0))
    probe = to_vector_literal(axis(0))
    with get_pool().connection() as conn:
        plan = "\n".join(
            r[0]
            for r in conn.execute(
                "EXPLAIN SELECT belief_id, status, created_at, embedding <=> %s::vector"
                " FROM beliefs ORDER BY embedding <=> %s::vector LIMIT 20",
                (probe, probe),
            ).fetchall()
        )
    assert "vector search" in plan, plan
    assert "beliefs_embedding_idx" in plan, plan


def test_ttl_expired_but_visible_belief_still_flips(fx, qs):
    """TTL deletes are blocked by derivation FKs; expired rows stay visible and
    must still join the closure (design review 2026-07-03)."""
    poison = fx.belief("researcher", "poisoned claim", source="forum")
    from services.common.db import get_pool

    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE beliefs SET ttl_expire_at = now() - INTERVAL '1 day' WHERE belief_id = %s",
            (poison["belief_id"],),
        )

    r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    assert r.json()["belief_count"] == 1
    assert statuses([poison["belief_id"]])[poison["belief_id"]] == "quarantined"


def test_atomicity_concurrent_reader_never_sees_partial_flip(fx, qs):
    """Deterministic all-or-nothing check: the recant transaction parks between
    flip and commit while a concurrent reader observes; it must see the OLD
    state (0 quarantined), never a partial flip. After commit: all N.

    The reader runs at PRIORITY HIGH so it does not block on the parked writer's
    write intents regardless of kv.transaction.write_buffering: its PUSH_TIMESTAMP
    succeeds immediately and it reads the pre-flip snapshot. reader_done separates
    the property under test (reader COMPLETED before commit) from a liveness
    failure, so a blocked reader fails as 'never completed pre-commit' instead of
    a bogus atomicity violation on the post-commit state (review 2026-07-03)."""
    poison = fx.belief("researcher", "poisoned claim", source="forum")
    child = fx.belief("support", "derived", parents=[poison["belief_id"]])
    ids = [poison["belief_id"], child["belief_id"]]

    import services.quarantine.app as qapp
    from services.common.db import get_pool

    parked = threading.Event()
    reader_done = threading.Event()
    observed: list[int] = []

    def reader():
        parked.wait(timeout=15)
        with get_pool().connection() as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION PRIORITY HIGH")
                n = conn.execute(
                    "SELECT count(*) FROM beliefs WHERE belief_id = ANY(%s::uuid[])"
                    " AND status = 'quarantined'",
                    (ids,),
                ).fetchone()[0]
        observed.append(int(n))
        reader_done.set()

    t = threading.Thread(target=reader)
    t.start()

    pre_commit = {"reader_done": False}

    def hook():
        parked.set()
        # The high-priority reader must finish against the parked (pre-commit)
        # writer; record whether it did so before this transaction commits.
        pre_commit["reader_done"] = reader_done.wait(timeout=10)

    qapp._after_flip_hook = hook
    try:
        r = qs.post("/recant", json={"source_id": fx.sources["forum"], "actor": "test"})
    finally:
        qapp._after_flip_hook = None
    t.join(timeout=15)

    assert r.status_code == 200
    assert pre_commit["reader_done"], "reader never completed before commit (liveness, not atomicity)"
    assert observed == [0], f"reader saw partial/early flip: {observed}"
    st = statuses(ids)
    assert all(v == "quarantined" for v in st.values())

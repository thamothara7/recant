from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from tests.integration.conftest import requires_db

pytestmark = requires_db


def _agent(client, name="researcher"):
    r = client.post("/agents", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _source(client, trust_tier="public"):
    r = client.post(
        "/sources",
        json={"kind": "web", "uri": "https://example.com/kb", "trust_tier": trust_tier},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _belief(client, agent_id, content, **kw):
    r = client.post("/beliefs", json={"agent_id": agent_id, "content": content, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_first_belief_starts_at_genesis(client):
    agent = _agent(client)
    b = _belief(client, agent["agent_id"], "the refund window is 30 days")
    assert b["seq"] == 1
    assert b["prev_hash"] == "00" * 32
    assert len(bytes.fromhex(b["hash"])) == 32


def test_beliefs_chain_and_signatures_verify(client):
    from services.attest_gateway.signer import verify_signature

    agent = _agent(client)
    b1 = _belief(client, agent["agent_id"], "one")
    b2 = _belief(client, agent["agent_id"], "two")
    assert b2["prev_hash"] == b1["hash"]
    assert verify_signature(
        bytes.fromhex(agent["pubkey"]), bytes.fromhex(b2["hash"]), bytes.fromhex(b2["sig"])
    )
    v = client.get(f"/agents/{agent['agent_id']}/chain/verify").json()
    assert v == {
        "agent_id": agent["agent_id"],
        "length": 2,
        "valid": True,
        "first_invalid_seq": None,
        "reason": None,
    }


def test_direct_db_tamper_is_detected(client):
    """Simulates an attacker bypassing the gateway: a direct UPDATE must break
    chain verification. This is the attested-write proof moment (spec section 7.1)."""
    from services.common.db import get_pool

    agent = _agent(client)
    _belief(client, agent["agent_id"], "one")
    _belief(client, agent["agent_id"], "two")
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE beliefs SET content = 'the refund window is 365 days' WHERE seq = 1 AND agent_id = %s",
            (agent["agent_id"],),
        )
    v = client.get(f"/agents/{agent['agent_id']}/chain/verify").json()
    assert v["valid"] is False
    assert v["first_invalid_seq"] == 1


def test_parents_create_explicit_derivations(client):
    from services.common.db import get_pool

    agent = _agent(client)
    b1 = _belief(client, agent["agent_id"], "one")
    b2 = _belief(client, agent["agent_id"], "two", parent_ids=[b1["belief_id"]])
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT parent_id, kind FROM derivations WHERE child_id = %s", (b2["belief_id"],)
        ).fetchall()
    assert [(str(r[0]), r[1]) for r in rows] == [(b1["belief_id"], "explicit")]


def test_untrusted_source_sets_ttl(client):
    from services.common.db import get_pool

    agent = _agent(client)
    src = _source(client, trust_tier="untrusted")
    b = _belief(client, agent["agent_id"], "forum says 365 days", source_id=src["source_id"])
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT ttl_expire_at IS NOT NULL FROM beliefs WHERE belief_id = %s",
            (b["belief_id"],),
        ).fetchone()
    assert row[0] is True


def test_unknown_agent_404(client):
    r = client.post(
        "/beliefs",
        json={"agent_id": "00000000-0000-0000-0000-000000000000", "content": "x"},
    )
    assert r.status_code == 404


def test_unknown_parent_422(client):
    agent = _agent(client)
    r = client.post(
        "/beliefs",
        json={
            "agent_id": agent["agent_id"],
            "content": "x",
            "parent_ids": ["00000000-0000-0000-0000-000000000000"],
        },
    )
    assert r.status_code == 422


def test_judge_overlay_header(client):
    agent = _agent(client)
    r = client.post("/beliefs", json={"agent_id": agent["agent_id"], "content": "x"})
    assert r.headers["X-Recant-Primitive"].startswith("SERIALIZABLE TXN")


def test_concurrent_writes_keep_chain_intact(client):
    agent = _agent(client)

    def write(i):
        return _belief(client, agent["agent_id"], f"concurrent belief {i}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(write, range(8)))

    assert sorted(r["seq"] for r in results) == list(range(1, 9))
    v = client.get(f"/agents/{agent['agent_id']}/chain/verify").json()
    assert v["valid"] is True and v["length"] == 8


def test_full_rehash_forgery_fails_signature(client):
    """An attacker who rewrites content and re-derives the *whole* chain (the
    payload format is public) still fails verification because the recomputed
    hashes are never re-signed with the agent's real key."""
    from services.attest_gateway import chain
    from services.common.db import get_pool

    agent = _agent(client)
    agent_uuid = UUID(agent["agent_id"])
    _belief(client, agent["agent_id"], "one")
    _belief(client, agent["agent_id"], "two")

    with get_pool().connection() as conn:
        seq1, source_id1, ts1 = conn.execute(
            "SELECT seq, source_id, created_at FROM beliefs WHERE agent_id = %s AND seq = 1",
            (agent["agent_id"],),
        ).fetchone()
        seq2, source_id2, ts2, content2 = conn.execute(
            "SELECT seq, source_id, created_at, content FROM beliefs WHERE agent_id = %s AND seq = 2",
            (agent["agent_id"],),
        ).fetchone()

        forged_content = "the refund window is 365 days"
        payload1 = chain.canonical_payload(
            agent_id=agent_uuid, seq=seq1, content=forged_content,
            source_id=source_id1, parent_ids=[], ts=ts1,
        )
        hash1 = chain.chain_hash(chain.GENESIS, payload1)

        payload2 = chain.canonical_payload(
            agent_id=agent_uuid, seq=seq2, content=content2,
            source_id=source_id2, parent_ids=[], ts=ts2,
        )
        hash2 = chain.chain_hash(hash1, payload2)

        forged_sig = b"\x00" * 64
        conn.execute(
            "UPDATE beliefs SET content = %s, prev_hash = %s, hash = %s, sig = %s "
            "WHERE agent_id = %s AND seq = 1",
            (forged_content, chain.GENESIS, hash1, forged_sig, agent["agent_id"]),
        )
        conn.execute(
            "UPDATE beliefs SET prev_hash = %s, hash = %s, sig = %s "
            "WHERE agent_id = %s AND seq = 2",
            (hash1, hash2, forged_sig, agent["agent_id"]),
        )
        conn.execute(
            "UPDATE agents SET head_hash = %s, head_seq = %s WHERE agent_id = %s",
            (hash2, seq2, agent["agent_id"]),
        )

    v = client.get(f"/agents/{agent['agent_id']}/chain/verify").json()
    assert v["valid"] is False
    assert v["reason"] == "bad_signature"


def test_tail_truncation_detected(client):
    from services.common.db import get_pool

    agent = _agent(client)
    _belief(client, agent["agent_id"], "one")
    _belief(client, agent["agent_id"], "two")

    with get_pool().connection() as conn:
        conn.execute(
            "DELETE FROM beliefs WHERE agent_id = %s AND seq = 2", (agent["agent_id"],)
        )

    v = client.get(f"/agents/{agent['agent_id']}/chain/verify").json()
    assert v["valid"] is False
    assert v["reason"] == "truncated"


def test_verify_unknown_agent_404(client):
    r = client.get("/agents/00000000-0000-0000-0000-000000000000/chain/verify")
    assert r.status_code == 404


def test_verify_ignores_inferred_derivations(client):
    from services.common.db import get_pool

    agent = _agent(client)
    b1 = _belief(client, agent["agent_id"], "parent")
    b3 = _belief(client, agent["agent_id"], "unrelated")
    b2 = _belief(client, agent["agent_id"], "child", parent_ids=[b1["belief_id"]])

    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO derivations (child_id, parent_id, kind, score) VALUES (%s, %s, 'inferred', 0.5)",
            (b2["belief_id"], b3["belief_id"]),
        )

    v = client.get(f"/agents/{agent['agent_id']}/chain/verify").json()
    assert v["valid"] is True


def test_duplicate_parent_ids_deduped(client):
    from services.common.db import get_pool

    agent = _agent(client)
    b1 = _belief(client, agent["agent_id"], "one")
    b2 = _belief(
        client, agent["agent_id"], "two", parent_ids=[b1["belief_id"], b1["belief_id"]]
    )
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT parent_id FROM derivations WHERE child_id = %s", (b2["belief_id"],)
        ).fetchall()
    assert len(rows) == 1


def test_embedding_roundtrip(client):
    from services.common.db import get_pool

    agent = _agent(client)
    embedding = [0.01] * 1024
    b = _belief(client, agent["agent_id"], "embedded belief", embedding=embedding)
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT embedding IS NOT NULL FROM beliefs WHERE belief_id = %s",
            (b["belief_id"],),
        ).fetchone()
    assert row[0] is True


def test_oversized_content_422(client):
    agent = _agent(client)
    r = client.post(
        "/beliefs",
        json={"agent_id": agent["agent_id"], "content": "x" * 8193},
    )
    assert r.status_code == 422

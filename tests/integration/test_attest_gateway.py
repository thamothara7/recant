from concurrent.futures import ThreadPoolExecutor

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

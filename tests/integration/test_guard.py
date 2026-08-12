"""End-to-end checks for proof-carrying action authorization."""

from tests.integration.conftest import requires_db

pytestmark = requires_db


def _agent(client, name="guard-agent"):
    response = client.post("/agents", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _source(client, trust_tier="public"):
    response = client.post(
        "/sources",
        json={
            "kind": "web",
            "uri": f"https://example.com/{trust_tier}",
            "trust_tier": trust_tier,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _belief(client, agent_id, content, **extra):
    response = client.post("/beliefs", json={"agent_id": agent_id, "content": content, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_context_receipt_propagates_and_attests_provenance(client, guard_client):
    agent = _agent(client)
    source = _source(client, "verified")
    parent = _belief(
        client,
        agent["agent_id"],
        "the vendor refund window is 30 days",
        source_id=source["source_id"],
    )

    receipt_response = guard_client.post(
        "/contexts/receipts",
        json={"agent_id": agent["agent_id"], "belief_ids": [parent["belief_id"]]},
    )
    assert receipt_response.status_code == 201, receipt_response.text
    receipt = receipt_response.json()

    child = _belief(
        client,
        agent["agent_id"],
        "answer the customer using the retrieved policy",
        context_receipt_id=receipt["receipt_id"],
    )
    assert child["authority_rank"] == source["authority_rank"] == 60
    assert child["origin_source_ids"] == [source["source_id"]]
    assert child["context_receipt_id"] == receipt["receipt_id"]
    assert child["provenance_method"] == "context_receipt"
    assert child["attestation_version"] == "v2"

    verification = client.get(f"/agents/{agent['agent_id']}/chain/verify")
    assert verification.status_code == 200
    assert verification.json()["valid"] is True


def test_permit_is_bound_to_exact_arguments_and_single_use(client, guard_client):
    agent = _agent(client)
    source = _source(client)
    belief = _belief(
        client,
        agent["agent_id"],
        "account 42 has an open support case",
        source_id=source["source_id"],
    )
    decision_response = guard_client.post(
        "/actions/authorize",
        json={
            "agent_id": agent["agent_id"],
            "tool_name": "read",
            "arguments": {"account_id": 42},
            "support_belief_ids": [belief["belief_id"]],
        },
    )
    assert decision_response.status_code == 201, decision_response.text
    decision = decision_response.json()
    assert decision["decision"] == "allow"
    assert decision["permit"]

    wrong = guard_client.post(
        "/actions/permits/consume",
        json={
            "permit": decision["permit"],
            "tool_name": "read",
            "arguments": {"account_id": 43},
        },
    )
    assert wrong.status_code == 409

    consumed = guard_client.post(
        "/actions/permits/consume",
        json={
            "permit": decision["permit"],
            "tool_name": "read",
            "arguments": {"account_id": 42},
        },
    )
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["status"] == "executed"

    replay = guard_client.post(
        "/actions/permits/consume",
        json={
            "permit": decision["permit"],
            "tool_name": "read",
            "arguments": {"account_id": 42},
        },
    )
    assert replay.status_code == 409
    assert replay.json()["detail"] == "permit was already consumed"


def test_idempotent_permit_replays_without_plaintext_database_copy(client, guard_client):
    from services.common.db import get_pool

    agent = _agent(client)
    source = _source(client)
    belief = _belief(
        client,
        agent["agent_id"],
        "account 42 has an open support case",
        source_id=source["source_id"],
    )
    headers = {"Idempotency-Key": "guard-permit-replay-001"}
    request = {
        "agent_id": agent["agent_id"],
        "tool_name": "read",
        "arguments": {"account_id": 42},
        "support_belief_ids": [belief["belief_id"]],
    }
    first = guard_client.post("/actions/authorize", json=request, headers=headers)
    replayed = guard_client.post("/actions/authorize", json=request, headers=headers)
    assert first.status_code == replayed.status_code == 201
    assert first.json() == replayed.json()
    permit = first.json()["permit"]
    assert permit

    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT response_body, response_ciphertext, response_nonce, encryption_version"
            " FROM idempotency_records WHERE idempotency_key = %s",
            (headers["Idempotency-Key"],),
        ).fetchone()
    assert row is not None
    assert row[0] == {}
    assert row[1] is not None and permit.encode() not in bytes(row[1])
    assert row[2] is not None and len(bytes(row[2])) == 12
    assert row[3] == "aesgcm-v1"


def test_low_authority_effect_requires_confirmation(client, guard_client):
    agent = _agent(client)
    source = _source(client)
    belief = _belief(
        client,
        agent["agent_id"],
        "customer 42 requested a refund",
        source_id=source["source_id"],
    )
    requested = guard_client.post(
        "/actions/authorize",
        json={
            "agent_id": agent["agent_id"],
            "tool_name": "refund",
            "arguments": {"account_id": 42, "amount": 25},
            "support_belief_ids": [belief["belief_id"]],
        },
    )
    assert requested.status_code == 201, requested.text
    pending = requested.json()
    assert pending["decision"] == "confirm"
    assert pending["permit"] is None

    confirmed_response = guard_client.post(
        f"/actions/decisions/{pending['decision_id']}/confirm",
        json={"reason": "support lead verified the customer request"},
    )
    assert confirmed_response.status_code == 201, confirmed_response.text
    confirmed = confirmed_response.json()
    assert confirmed["decision"] == "allow"
    assert confirmed["supersedes_decision_id"] == pending["decision_id"]
    assert confirmed["observed_authority"] == 70
    assert confirmed["permit"]


def test_recant_revokes_unconsumed_permit(client, guard_client, quarantine_client):
    agent = _agent(client)
    source = _source(client, "untrusted")
    belief = _belief(
        client,
        agent["agent_id"],
        "forum claim used by a read operation",
        source_id=source["source_id"],
    )
    authorized = guard_client.post(
        "/actions/authorize",
        json={
            "agent_id": agent["agent_id"],
            "tool_name": "read",
            "arguments": {"query": "claim"},
            "support_belief_ids": [belief["belief_id"]],
        },
    ).json()
    assert authorized["decision"] == "allow"

    recanted = quarantine_client.post(
        "/recant", json={"source_id": source["source_id"], "actor": "test"}
    )
    assert recanted.status_code == 200, recanted.text

    consumed = guard_client.post(
        "/actions/permits/consume",
        json={
            "permit": authorized["permit"],
            "tool_name": "read",
            "arguments": {"query": "claim"},
        },
    )
    assert consumed.status_code == 409
    assert consumed.json()["detail"] == "permit was revoked"


def test_mutations_replay_by_idempotency_key(client):
    headers = {"Idempotency-Key": "agent-create-001"}
    first = client.post("/agents", json={"name": "stable"}, headers=headers)
    second = client.post("/agents", json={"name": "stable"}, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()

    conflict = client.post("/agents", json={"name": "different"}, headers=headers)
    assert conflict.status_code == 409


def test_expired_idempotency_key_can_be_reclaimed(client):
    from services.common.db import run_txn

    headers = {"Idempotency-Key": "agent-expired-001"}
    first = client.post("/agents", json={"name": "before-expiry"}, headers=headers)
    assert first.status_code == 201
    run_txn(
        lambda conn: conn.execute(
            "UPDATE idempotency_records SET expires_at = now() - INTERVAL '1 second'"
            " WHERE idempotency_key = 'agent-expired-001'"
        )
    )
    reclaimed = client.post("/agents", json={"name": "after-expiry"}, headers=headers)
    assert reclaimed.status_code == 201, reclaimed.text
    assert reclaimed.json()["name"] == "after-expiry"


def test_tampering_propagated_authority_breaks_v2_chain(client):
    from services.common.db import get_pool

    agent = _agent(client)
    source = _source(client)
    belief = _belief(
        client,
        agent["agent_id"],
        "public claim",
        source_id=source["source_id"],
    )
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE beliefs SET authority_rank = 90 WHERE belief_id = %s",
            (belief["belief_id"],),
        )

    verification = client.get(f"/agents/{agent['agent_id']}/chain/verify")
    assert verification.status_code == 200
    assert verification.json()["valid"] is False
    assert verification.json()["reason"] == "hash_mismatch"


def test_guard_rejects_tampered_belief_authority(client, guard_client):
    from services.common.db import get_pool

    agent = _agent(client)
    source = _source(client, "public")
    belief = _belief(
        client,
        agent["agent_id"],
        "a public claim cannot become verified by editing a row",
        source_id=source["source_id"],
    )
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE beliefs SET authority_rank = 90 WHERE belief_id = %s",
            (belief["belief_id"],),
        )

    response = guard_client.post(
        "/actions/authorize",
        json={
            "agent_id": agent["agent_id"],
            "tool_name": "read",
            "arguments": {"query": "claim"},
            "support_belief_ids": [belief["belief_id"]],
        },
    )
    assert response.status_code == 409
    assert "attestation verification" in response.json()["detail"]


def test_confirmation_rejects_tampered_original_decision(client, guard_client):
    from services.common.db import get_pool

    agent = _agent(client)
    source = _source(client, "public")
    belief = _belief(
        client,
        agent["agent_id"],
        "refund request needs confirmation",
        source_id=source["source_id"],
    )
    pending = guard_client.post(
        "/actions/authorize",
        json={
            "agent_id": agent["agent_id"],
            "tool_name": "refund",
            "arguments": {"amount": 25},
            "support_belief_ids": [belief["belief_id"]],
        },
    ).json()
    assert pending["decision"] == "confirm"
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE action_decisions SET reason = 'forged reason' WHERE decision_id = %s",
            (pending["decision_id"],),
        )

    response = guard_client.post(
        f"/actions/decisions/{pending['decision_id']}/confirm",
        json={"reason": "operator checked the request"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "original decision attestation is invalid"


def test_permit_rejects_tampered_stored_expiry(client, guard_client):
    from services.common.db import get_pool

    agent = _agent(client)
    source = _source(client, "public")
    belief = _belief(
        client,
        agent["agent_id"],
        "read evidence",
        source_id=source["source_id"],
    )
    allowed = guard_client.post(
        "/actions/authorize",
        json={
            "agent_id": agent["agent_id"],
            "tool_name": "read",
            "arguments": {"query": "evidence"},
            "support_belief_ids": [belief["belief_id"]],
        },
    ).json()
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE action_permits SET expires_at = expires_at + INTERVAL '1 minute'"
            " WHERE permit_id = %s",
            (allowed["permit_id"],),
        )

    response = guard_client.post(
        "/actions/permits/consume",
        json={
            "permit": allowed["permit"],
            "tool_name": "read",
            "arguments": {"query": "evidence"},
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "permit signature is invalid"

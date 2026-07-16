"""The client is the public integration surface, so pin the exact requests it
sends and how it reads responses. httpx.MockTransport routes by path: no network,
no running services, always runs."""

import json
from uuid import uuid4

import httpx
import pytest

from recant_client import RecantClient, RecantError

AGENT = str(uuid4())
SOURCE = str(uuid4())
BELIEF = str(uuid4())
INCIDENT = str(uuid4())

# Captured requests, so tests can assert on method/path/body.
seen: list[httpx.Request] = []


def _handler(request: httpx.Request) -> httpx.Response:
    seen.append(request)
    path = request.url.path
    method = request.method
    if method == "POST" and path == "/agents":
        return httpx.Response(201, json={"agent_id": AGENT, "name": "support-bot"})
    if method == "POST" and path == "/sources":
        return httpx.Response(201, json={"source_id": SOURCE, "trust_tier": "verified"})
    if method == "POST" and path == "/beliefs":
        return httpx.Response(201, json={"belief_id": BELIEF, "seq": 1})
    if method == "POST" and path == "/recant":
        return httpx.Response(
            200,
            json={
                "incident_id": INCIDENT,
                "closure_ids": [BELIEF, str(uuid4()), str(uuid4())],
                "newly_flipped_ids": [BELIEF],
                "agent_ids": [AGENT],
            },
        )
    if method == "POST" and path == "/taint/preview":
        return httpx.Response(200, json={"closure_ids": [BELIEF], "would_flip": 1, "agent_ids": [AGENT]})
    if method == "GET" and path == f"/agents/{AGENT}/chain/verify":
        return httpx.Response(200, json={"valid": True, "chain_length": 1})
    if method == "GET" and path == f"/beliefs/{BELIEF}/provenance":
        return httpx.Response(200, json={"chain_valid": True, "sig_valid": True})
    if method == "GET" and path == f"/incidents/{INCIDENT}/affidavit":
        return httpx.Response(200, json={"text": "INCIDENT AFFIDAVIT\n..."})
    if method == "GET" and path == f"/agents/{AGENT}/beliefs":
        return httpx.Response(200, json={"beliefs": [], "as_of": request.url.params.get("as_of")})
    return httpx.Response(404, text="unmapped")


@pytest.fixture
def client():
    seen.clear()
    c = RecantClient(transport=httpx.MockTransport(_handler))
    yield c
    c.close()


def test_register_and_remember_hit_the_gateway(client):
    assert client.register_agent("support-bot", region="us-east") == AGENT
    assert client.register_source("https://vendor.com/x", "verified") == SOURCE
    bid = client.remember(AGENT, "The refund window is 30 days.", source_id=SOURCE, parent_ids=[BELIEF])
    assert bid == BELIEF

    agent_req, source_req, belief_req = seen
    assert json.loads(agent_req.content) == {"name": "support-bot", "region": "us-east"}
    assert json.loads(source_req.content)["trust_tier"] == "verified"
    body = json.loads(belief_req.content)
    assert body["agent_id"] == AGENT
    assert body["source_id"] == SOURCE
    assert body["parent_ids"] == [BELIEF]
    # Omitted embedding must not be sent (server embeds it).
    assert "embedding" not in body


def test_remember_omits_empty_provenance(client):
    client.remember(AGENT, "a first note")
    body = json.loads(seen[-1].content)
    assert body == {"agent_id": AGENT, "content": "a first note"}


def test_recant_returns_receipt(client):
    receipt = client.recant(SOURCE, actor="oncall")
    assert receipt["incident_id"] == INCIDENT
    assert len(receipt["closure_ids"]) == 3
    assert json.loads(seen[-1].content) == {"source_id": SOURCE, "actor": "oncall"}


def test_preview_is_read_only(client):
    p = client.preview(SOURCE)
    assert p["would_flip"] == 1
    assert seen[-1].url.path == "/taint/preview"


def test_verify_and_provenance_and_affidavit(client):
    assert client.verify_chain(AGENT)["valid"] is True
    assert client.provenance(BELIEF)["sig_valid"] is True
    assert client.affidavit(INCIDENT).startswith("INCIDENT AFFIDAVIT")


def test_beliefs_at_passes_as_of(client):
    client.beliefs_at(AGENT, as_of="2026-07-16T14:32:00+00:00")
    assert seen[-1].url.params.get("as_of") == "2026-07-16T14:32:00+00:00"


def test_non_2xx_raises_recant_error(client):
    with pytest.raises(RecantError, match="404"):
        client.incident("does-not-exist")  # routes to 404 in the handler

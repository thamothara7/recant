"""httpx client for the attest gateway (W3 plan section 4).

The gateway remains the only write path into custody, even for the fleet.
Tests pass an httpx client built on ASGITransport against the app in-process;
the CLI builds a network client from RECANT_GATEWAY_URL. Same code either way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

import httpx


class AlreadySeeded(RuntimeError):
    """The database already contains this story (deterministic demos never upsert)."""


@dataclass(frozen=True)
class BeliefReceipt:
    belief_id: UUID
    status: str
    seq: int


class GatewayClient:
    def __init__(self, client: httpx.Client | None = None):
        # Read the gateway URL when the client is built, not at import: the CLI
        # may set RECANT_GATEWAY_URL after this module loads. Tests inject a
        # client and never touch the network path.
        base = os.environ.get("RECANT_GATEWAY_URL", "http://localhost:8000")
        self.http = client if client is not None else httpx.Client(base_url=base, timeout=10)

    def create_agent(self, name: str) -> UUID:
        r = self.http.post("/agents", json={"name": name})
        if r.status_code == 409:
            raise AlreadySeeded(f"agent {name} already exists; run against a clean database")
        r.raise_for_status()
        return UUID(r.json()["agent_id"])

    def create_source(self, kind: str, uri: str, trust_tier: str) -> UUID:
        r = self.http.post("/sources", json={"kind": kind, "uri": uri, "trust_tier": trust_tier})
        r.raise_for_status()
        return UUID(r.json()["source_id"])

    def create_belief(
        self,
        agent_id: UUID,
        content: str,
        *,
        source_id: UUID | None = None,
        parent_ids: list[UUID] | None = None,
        embedding: list[float] | None = None,
    ) -> BeliefReceipt:
        r = self.http.post(
            "/beliefs",
            json={
                "agent_id": str(agent_id),
                "content": content,
                "source_id": str(source_id) if source_id else None,
                "parent_ids": [str(p) for p in (parent_ids or [])],
                "embedding": embedding,
            },
        )
        r.raise_for_status()
        body = r.json()
        return BeliefReceipt(belief_id=UUID(body["belief_id"]), status=body["status"], seq=body["seq"])

    def verify_chain(self, agent_id: UUID) -> dict:
        r = self.http.get(f"/agents/{agent_id}/chain/verify")
        r.raise_for_status()
        return r.json()

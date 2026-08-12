"""recant-client: integrate an agent fleet with Recant in one import.

Recant is a memory substrate your agents write through and query. The only
integration is: write every belief through ``remember`` instead of a raw vector
store (custody, hash-chaining, and the signature happen server-side), and call
``recant`` when a source turns out to be poisoned. Everything else is reads.

    from recant_client import RecantClient

    rc = RecantClient()  # defaults to the four local services

    agent = rc.register_agent("support-bot", region="us-east")
    source = rc.register_source("https://vendor.com/refund-policy", "verified")
    belief = rc.remember(agent, "The refund window is 30 days.", source_id=source)

    # ... later, the source is found poisoned ...
    incident = rc.recant(source)          # revokes it everywhere, provably
    print(rc.affidavit(incident["incident_id"]))

The four services (gateway, quarantine, forensics, Guard) are independent;
point the client at wherever they run. Only the standard library plus httpx is
required.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import httpx


class RecantError(RuntimeError):
    """A Recant service returned a non-2xx response."""


class RecantClient:
    def __init__(
        self,
        gateway: str = "http://localhost:8000",
        quarantine: str = "http://localhost:8001",
        forensics: str = "http://localhost:8002",
        guard: str = "http://localhost:8003",
        *,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        # transport is an injection seam for tests (httpx.MockTransport).
        self._gateway = gateway.rstrip("/")
        self._quarantine = quarantine.rstrip("/")
        self._forensics = forensics.rstrip("/")
        self._guard = guard.rstrip("/")
        self._token = token or os.environ.get("RECANT_API_TOKEN")
        self._http = httpx.Client(transport=transport, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "RecantClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals ----------------------------------------------------------

    def _request(self, method: str, url: str, **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}) or {})
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if headers:
            kw["headers"] = headers
        try:
            resp = self._http.request(method, url, **kw)
        except httpx.HTTPError as exc:  # network, timeout, DNS
            raise RecantError(f"{method} {url} failed: {exc}") from exc
        if resp.status_code >= 300:
            raise RecantError(f"{method} {url} -> {resp.status_code}: {resp.text[:200]}")
        return resp.json() if resp.content else None

    # -- write path (the whole integration) ---------------------------------

    @staticmethod
    def _idempotency_headers(key: str | None) -> dict[str, str]:
        return {"Idempotency-Key": key or f"recant-client-{uuid4()}"}

    def register_agent(
        self,
        name: str,
        region: str = "local",
        *,
        kms_key_arn: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Create an agent and return its id."""
        payload = {"name": name, "region": region}
        if kms_key_arn:
            payload["kms_key_arn"] = kms_key_arn
        body = self._request(
            "POST",
            f"{self._gateway}/agents",
            json=payload,
            headers=self._idempotency_headers(idempotency_key),
        )
        return body["agent_id"]

    def register_source(
        self,
        uri: str,
        trust_tier: str,
        kind: str = "web",
        region: str = "local",
        *,
        idempotency_key: str | None = None,
    ) -> str:
        """Create a source; returns its id. trust_tier is one of
        verified|partner|public|untrusted."""
        body = self._request(
            "POST",
            f"{self._gateway}/sources",
            json={"uri": uri, "trust_tier": trust_tier, "kind": kind, "region": region},
            headers=self._idempotency_headers(idempotency_key),
        )
        return body["source_id"]

    def remember(
        self,
        agent_id: str | UUID,
        content: str,
        *,
        source_id: str | UUID | None = None,
        parent_ids: list[str | UUID] | None = None,
        embedding: list[float] | None = None,
        context_receipt_id: str | UUID | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Write one belief through the attested gateway; returns its id.

        Pass source_id for provenance to an external source and parent_ids for
        provenance to earlier beliefs (either or both). Omit embedding to let
        Recant embed the content; pass a 1024-float vector to supply your own.
        """
        payload: dict[str, Any] = {"agent_id": str(agent_id), "content": content}
        if source_id is not None:
            payload["source_id"] = str(source_id)
        if parent_ids:
            payload["parent_ids"] = [str(p) for p in parent_ids]
        if embedding is not None:
            payload["embedding"] = embedding
        if context_receipt_id is not None:
            payload["context_receipt_id"] = str(context_receipt_id)
        body = self._request(
            "POST",
            f"{self._gateway}/beliefs",
            json=payload,
            headers=self._idempotency_headers(idempotency_key),
        )
        return body["belief_id"]

    # -- recant -------------------------------------------------------------

    def recant(
        self,
        source_id: str | UUID,
        actor: str = "operator",
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        """Revoke a source everywhere: quarantine its full contamination
        closure (including reworded copies with no explicit edge) and revoke
        unused permits in one serializable transaction. Durable fanout evicts
        runtime memory and aborts pending action rows. Returns the receipt
        (incident_id, closure_ids, newly_flipped_ids, agent_ids, ...)."""
        return self._request(
            "POST",
            f"{self._quarantine}/recant",
            json={"source_id": str(source_id), "actor": actor},
            headers=self._idempotency_headers(idempotency_key),
        )

    # -- Recant Guard -------------------------------------------------------

    def context_receipt(
        self,
        agent_id: str | UUID,
        belief_ids: list[str | UUID],
        *,
        ttl_seconds: int = 300,
        idempotency_key: str | None = None,
    ) -> dict:
        """Bind retrieved beliefs to a short-lived signed context receipt."""
        return self._request(
            "POST",
            f"{self._guard}/contexts/receipts",
            json={
                "agent_id": str(agent_id),
                "belief_ids": [str(value) for value in belief_ids],
                "ttl_seconds": ttl_seconds,
            },
            headers=self._idempotency_headers(idempotency_key),
        )

    def authorize_action(
        self,
        agent_id: str | UUID,
        tool_name: str,
        arguments: dict,
        *,
        support_belief_ids: list[str | UUID] | None = None,
        context_receipt_id: str | UUID | None = None,
        annotations: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "agent_id": str(agent_id),
            "tool_name": tool_name,
            "arguments": arguments,
            "support_belief_ids": [str(value) for value in (support_belief_ids or [])],
        }
        if context_receipt_id is not None:
            payload["context_receipt_id"] = str(context_receipt_id)
        if annotations is not None:
            payload["annotations"] = annotations
        return self._request(
            "POST",
            f"{self._guard}/actions/authorize",
            json=payload,
            headers=self._idempotency_headers(idempotency_key),
        )

    def confirm_action(
        self,
        decision_id: str | UUID,
        reason: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        return self._request(
            "POST",
            f"{self._guard}/actions/decisions/{decision_id}/confirm",
            json={"reason": reason},
            headers=self._idempotency_headers(idempotency_key),
        )

    def consume_permit(self, permit: str, tool_name: str, arguments: dict) -> dict:
        """Atomically validate and consume a permit immediately before a tool call."""
        return self._request(
            "POST",
            f"{self._guard}/actions/permits/consume",
            json={"permit": permit, "tool_name": tool_name, "arguments": arguments},
        )

    def action_decision(self, decision_id: str | UUID) -> dict:
        return self._request("GET", f"{self._guard}/actions/decisions/{decision_id}")

    def checkpoint(self) -> dict:
        return self._request("POST", f"{self._forensics}/checkpoints")

    def preview(self, source_id: str | UUID) -> dict:
        """Read-only: what a recant of this source WOULD flip (closure_ids,
        would_flip, agent_ids), without changing anything."""
        return self._request(
            "POST", f"{self._quarantine}/taint/preview", json={"source_id": str(source_id)}
        )

    # -- reads / proof ------------------------------------------------------

    def verify_chain(self, agent_id: str | UUID) -> dict:
        """Verify an agent's hash chain and signatures end to end."""
        return self._request("GET", f"{self._gateway}/agents/{agent_id}/chain/verify")

    def board(self) -> dict:
        """The whole provenance graph (agents, sources, beliefs, derivations)."""
        return self._request("GET", f"{self._forensics}/board")

    def beliefs_at(self, agent_id: str | UUID, as_of: str | None = None) -> dict:
        """An agent's beliefs now, or at a past timestamp (AS OF SYSTEM TIME).
        as_of is an ISO-8601 timestamp; omit for the current view."""
        params = {"as_of": as_of} if as_of else None
        return self._request("GET", f"{self._forensics}/agents/{agent_id}/beliefs", params=params)

    def provenance(self, belief_id: str | UUID) -> dict:
        """One belief's provenance: source, parents, children, and live chain +
        signature verification."""
        return self._request("GET", f"{self._forensics}/beliefs/{belief_id}/provenance")

    def custody_chain(self, agent_id: str | UUID) -> dict:
        """An agent's full custody chain with derivation edges and verification."""
        return self._request("GET", f"{self._forensics}/agents/{agent_id}/custody-chain")

    def incident(self, incident_id: str | UUID) -> dict:
        """An incident summary: source, closure, per-agent impact, and the
        quarantine actions re-verified from stored rows."""
        return self._request("GET", f"{self._forensics}/incidents/{incident_id}")

    def affidavit(self, incident_id: str | UUID) -> str:
        """The incident affidavit text (Bedrock Claude, or the template fallback)."""
        return self._request("GET", f"{self._forensics}/incidents/{incident_id}/affidavit")["text"]

    def archive(self, incident_id: str | UUID) -> dict:
        """Write the incident's evidence bundle to S3; returns the keys written."""
        return self._request("POST", f"{self._forensics}/incidents/{incident_id}/archive")

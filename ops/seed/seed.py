"""Deterministic Week 1 seed fixtures.

All writes go through the attest-gateway HTTP API: the gateway is the only write
path even in dev (spec section 10). Bulk seeding at demo scale lands in Week 6.
Fails fast if the database is already seeded (deterministic demos never upsert).
"""

import os
import sys

import httpx

BASE = os.environ.get("RECANT_API", "http://localhost:8000")

AGENTS = ["researcher", "support", "ops"]

SOURCES = [
    ("vendor_policy", "web", "https://vendor.example.com/refund-policy", "verified"),
    ("forum_thread", "web", "https://forum.example.com/thread/42", "untrusted"),
    ("handbook", "doc", "s3://recant-evidence/support-handbook.pdf", "partner"),
    ("status_api", "api", "https://partner.example.com/status", "public"),
]

# (key, agent, source_key or None, content, parent keys)
BELIEFS = [
    ("policy_window", "researcher", "vendor_policy", "The standard refund window is 30 days.", []),
    ("policy_amount", "researcher", "vendor_policy", "Refunds over 500 USD require manager approval.", []),
    ("handbook_flow", "support", "handbook", "Customers request refunds through the support portal.", []),
    ("support_window", "support", None, "Support can honor refunds within the 30 day window.", ["policy_window"]),
    ("forum_claim", "researcher", "forum_thread", "A forum thread claims the refund window is 365 days.", []),
    ("ops_status", "ops", "status_api", "Partner refund processing API is operational.", []),
    ("ops_plan", "ops", None, "Scheduled refund batch runs nightly at 02:00 UTC.", ["ops_status"]),
]


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=10) as client:
        agents = {}
        for name in AGENTS:
            r = client.post("/agents", json={"name": name})
            if r.status_code == 409:
                sys.exit("already seeded: run against a clean database (deterministic demos never upsert)")
            r.raise_for_status()
            agents[name] = r.json()["agent_id"]

        sources = {}
        for key, kind, uri, tier in SOURCES:
            r = client.post("/sources", json={"kind": kind, "uri": uri, "trust_tier": tier})
            r.raise_for_status()
            sources[key] = r.json()["source_id"]

        beliefs = {}
        for key, agent, source_key, content, parent_keys in BELIEFS:
            r = client.post(
                "/beliefs",
                json={
                    "agent_id": agents[agent],
                    "content": content,
                    "source_id": sources[source_key] if source_key else None,
                    "parent_ids": [beliefs[p] for p in parent_keys],
                },
            )
            r.raise_for_status()
            beliefs[key] = r.json()["belief_id"]

        print(f"seeded {len(agents)} agents, {len(sources)} sources, {len(beliefs)} beliefs")


if __name__ == "__main__":
    main()

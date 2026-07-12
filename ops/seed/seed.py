"""Deterministic seed fixtures (W1 story + W2 contamination beliefs).

All writes go through the attest-gateway HTTP API: the gateway is the only
write path even in dev (spec section 10). The story itself (agents, sources,
beliefs, controlled embeddings, check_story) lives in fleet/story.py, shared
with the W3 fleet so seeder and fleet cannot drift. Fails fast if the database
is already seeded (deterministic demos never upsert). Bulk seeding at demo
scale lands in Week 6.
"""

import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fleet.story import AGENTS, BELIEFS, EMBEDDINGS, SOURCES, check_story  # noqa: E402

BASE = os.environ.get("RECANT_API", "http://localhost:8000")


def main() -> None:
    check_story()

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
                    "embedding": EMBEDDINGS[key],
                },
            )
            r.raise_for_status()
            beliefs[key] = r.json()["belief_id"]

        print(f"seeded {len(agents)} agents, {len(sources)} sources, {len(beliefs)} beliefs")
        print(f"recant target: sources[forum_thread] = {sources['forum_thread']}")


if __name__ == "__main__":
    main()

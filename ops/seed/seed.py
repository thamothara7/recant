"""Deterministic seed fixtures (W1 story + W2 contamination beliefs).

All writes go through the attest-gateway HTTP API: the gateway is the only write
path even in dev (spec section 10). Story beliefs carry CONTROLLED embeddings
(basis-vector mixtures, exactly like the integration tests): a lexical fake
cannot separate "same claim reworded" from "same topic, different claim" — the
live run on 2026-07-03 quarantined the clean 30-day policy at any threshold that
also caught the paraphrase. Real semantic separation arrives with Bedrock Titan
in W3; until then the demo story is pinned by construction, and check_story
proves both directions (paraphrase caught, every clean belief clear) before a
single row is written. Bulk seeding at demo scale lands in Week 6. Fails fast if
the database is already seeded (deterministic demos never upsert).
"""

import math
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.common.embedder import DIMENSIONS, cosine  # noqa: E402
from services.taint_engine.engine import default_threshold  # noqa: E402

BASE = os.environ.get("RECANT_API", "http://localhost:8000")

AGENTS = ["researcher", "support", "ops"]

SOURCES = [
    ("vendor_policy", "web", "https://vendor.example.com/refund-policy", "verified"),
    ("forum_thread", "web", "https://forum.example.com/thread/42", "untrusted"),
    ("handbook", "doc", "s3://recant-evidence/support-handbook.pdf", "partner"),
    ("status_api", "api", "https://partner.example.com/status", "public"),
]


def _axis(i: int) -> list[float]:
    v = [0.0] * DIMENSIONS
    v[i] = 1.0
    return v


def _mix(i: int, j: int, similarity_to_i: float) -> list[float]:
    v = [0.0] * DIMENSIONS
    v[i] = similarity_to_i
    v[j] = math.sqrt(1.0 - similarity_to_i**2)
    return v


# Topic axes 0-5; mixture remainders live on PRIVATE axes (100+) so a shared
# remainder can never manufacture similarity between unrelated beliefs (the
# first draft reused axis 5 and check_story caught ops_action <-> policy_amount
# at 0.98 before a row was written).
# The poison<->paraphrase pair sits at 0.91 (the console fixture's cosine);
# everything clean stays orthogonal to axis 0 or far below threshold on it.
EMBEDDINGS = {
    "policy_window": _axis(2),
    "policy_amount": _axis(5),
    "handbook_flow": _axis(3),
    "support_window": _mix(2, 100, 0.85),
    "forum_claim": _axis(0),
    "support_paraphrase": _mix(0, 101, 0.91),
    "ops_action": _mix(0, 102, 0.20),
    "ops_status": _axis(4),
    "ops_plan": _mix(4, 103, 0.70),
}

# (key, agent, source_key or None, content, parent keys)
# support_paraphrase deliberately has NO parents and NO source: proof moment 2
# is contamination with no recorded provenance, caught only by the vector kNN.
BELIEFS = [
    ("policy_window", "researcher", "vendor_policy", "The standard refund window is 30 days.", []),
    ("policy_amount", "researcher", "vendor_policy", "Refunds over 500 USD require manager approval.", []),
    ("handbook_flow", "support", "handbook", "Customers request refunds through the support portal.", []),
    ("support_window", "support", None, "Support can honor refunds within the 30 day window.", ["policy_window"]),
    ("forum_claim", "researcher", "forum_thread", "A forum thread claims the refund window is 365 days.", []),
    ("support_paraphrase", "support", None, "We can extend refunds up to a year for loyal customers.", []),
    ("ops_action", "ops", None, "Auto-approve pending 365-day refund for customer #4471.", ["support_paraphrase"]),
    ("ops_status", "ops", "status_api", "Partner refund processing API is operational.", []),
    ("ops_plan", "ops", None, "Scheduled refund batch runs nightly at 02:00 UTC.", ["ops_status"]),
]

# Contamination = seeds + explicit descendants + the vector-caught paraphrase.
TAINTED = {"forum_claim", "support_paraphrase", "ops_action"}


def check_story() -> None:
    """Prove the story before writing it: the paraphrase must clear the taint
    threshold against the poison, and NO clean belief may clear it against any
    tainted one (the 2026-07-03 live run failed exactly this second half)."""
    threshold = default_threshold()
    poison = EMBEDDINGS["forum_claim"]
    sim = cosine(EMBEDDINGS["support_paraphrase"], poison)
    if sim < threshold:
        sys.exit(f"seed story broken: paraphrase similarity {sim:.3f} < threshold {threshold}")
    for key, vec in EMBEDDINGS.items():
        if key in TAINTED:
            continue
        for tkey in TAINTED:
            s = cosine(vec, EMBEDDINGS[tkey])
            if s >= threshold:
                sys.exit(
                    f"seed story broken: clean belief {key} scores {s:.3f} >= threshold"
                    f" {threshold} against tainted {tkey}; recant would quarantine it"
                )


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

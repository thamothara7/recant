"""The demo story, in one place (W3 plan section 4).

Extracted from ops/seed/seed.py so the seeder and the fleet cannot drift: both
write the same agents, sources, beliefs, controlled embeddings, and edge
script, and check_story() proves both directions of the taint threshold before
either writes a row.

Story beliefs carry CONTROLLED embeddings (basis-vector mixtures): a lexical
fake cannot separate "same claim reworded" from "same topic, different claim"
(the 2026-07-03 live run quarantined the clean 30-day policy at any threshold
that also caught the paraphrase). Real semantic separation arrives with
Bedrock Titan under U3; until then the story is pinned by construction.
"""

from __future__ import annotations

import math
import sys

from services.common.embedder import DIMENSIONS, cosine
from services.taint_engine.engine import default_threshold

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

# The pending side effect ops queues on the tainted basis (proof moment 4's
# local rehearsal): the eviction worker must abort it when forum_thread is
# recanted, because derived_from overlaps the flipped ids.
ACTION = {
    "agent": "ops",
    "kind": "refund",
    "payload": {"customer": "#4471", "days": 365, "note": "auto-approve pending refund"},
    "derived_from_keys": ["ops_action", "support_paraphrase"],
}

# The fleet's deterministic tick script (plan section 4): the tick loop IS the
# story generator. Each entry is (tick, agent, op, key) where op is one of
# "ingest" (belief with a source), "derive" (belief with parents), "enqueue"
# (the agent_actions row). Running --ticks N executes the prefix tick <= N.
TICKS = [
    (1, "researcher", "ingest", "policy_window"),
    (1, "researcher", "ingest", "policy_amount"),
    (1, "support", "ingest", "handbook_flow"),
    (1, "ops", "ingest", "ops_status"),
    (2, "support", "derive", "support_window"),
    (2, "ops", "derive", "ops_plan"),
    (3, "researcher", "ingest", "forum_claim"),
    (3, "support", "derive", "support_paraphrase"),
    (4, "ops", "derive", "ops_action"),
    (4, "ops", "enqueue", "refund"),
]

MAX_TICK = max(t for t, _, _, _ in TICKS)


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

"""Scale stress test: does the recant hold at volume?

Builds a large fleet and a deep-and-wide contamination tree (explicit
derivation edges, so the closure is deterministic), plus a body of unrelated
clean beliefs as noise, then runs one recant and asserts it flips exactly the
contaminated closure in a single serializable transaction, leaving every clean
belief untouched. Prints the sizes and the recant latency.

DESTRUCTIVE: truncates every table first, so run it against the LOCAL cluster
only (the same guard as the integration suite). Needs DATABASE_URL and a live
cluster; no running services required (it drives the apps in-process).

    export DATABASE_URL=postgresql://root@localhost:26257/recant?sslmode=disable
    uv run python ops/scale_test.py                    # defaults: 20 agents, 300 tainted, 500 clean
    SCALE_AGENTS=40 SCALE_TAINTED=800 SCALE_NOISE=1200 uv run python ops/scale_test.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from services.attest_gateway.app import app as gateway_app  # noqa: E402
from services.common.db import run_txn  # noqa: E402
from services.quarantine.app import app as quarantine_app  # noqa: E402

AGENTS = int(os.environ.get("SCALE_AGENTS", "20"))
TAINTED = int(os.environ.get("SCALE_TAINTED", "300"))
NOISE = int(os.environ.get("SCALE_NOISE", "500"))
BRANCH = int(os.environ.get("SCALE_BRANCH", "3"))

_TABLES = [
    "derivations", "fanout_deliveries", "agent_actions", "quarantine_actions",
    "memory_events", "incidents", "beliefs", "sources", "agents", "agent_memory",
]


def _truncate() -> None:
    def txn(conn):
        for t in _TABLES:
            conn.execute(f"DELETE FROM {t}")
    run_txn(txn)


def main() -> None:
    if "localhost" not in os.environ.get("DATABASE_URL", "") and "127.0.0.1" not in os.environ.get("DATABASE_URL", ""):
        raise SystemExit("refusing to run: DATABASE_URL is not local (this truncates every table)")

    gw = TestClient(gateway_app)
    q = TestClient(quarantine_app)

    print(f"scale: {AGENTS} agents, {TAINTED} tainted (branch {BRANCH}), {NOISE} clean noise")
    _truncate()

    t_seed = time.perf_counter()
    agents = [
        gw.post("/agents", json={"name": f"scale-agent-{i}"}).json()["agent_id"]
        for i in range(AGENTS)
    ]
    bad = gw.post(
        "/sources",
        json={"kind": "web", "uri": "https://forum.example.com/poison", "trust_tier": "untrusted"},
    ).json()["source_id"]
    good = gw.post(
        "/sources",
        json={"kind": "web", "uri": "https://vendor.example.com/policy", "trust_tier": "verified"},
    ).json()["source_id"]

    def belief(agent: str, content: str, *, source_id=None, parents=None) -> str:
        body: dict = {"agent_id": agent, "content": content}
        if source_id:
            body["source_id"] = source_id
        if parents:
            body["parent_ids"] = parents
        r = gw.post("/beliefs", json=body)
        assert r.status_code == 201, r.text
        return r.json()["belief_id"]

    # Contamination tree: a root cites the poisoned source; each level derives
    # from the last via explicit edges, spread across the whole fleet.
    root = belief(agents[0], "poisoned root: the refund window is 365 days", source_id=bad)
    tainted = [root]
    frontier = [root]
    while len(tainted) < TAINTED:
        parent = frontier.pop(0)
        for _ in range(BRANCH):
            if len(tainted) >= TAINTED:
                break
            child = belief(
                agents[len(tainted) % AGENTS],
                f"reworded copy #{len(tainted)} of the poisoned claim",
                parents=[parent],
            )
            tainted.append(child)
            frontier.append(child)

    # Noise: unrelated clean beliefs from a trusted source, no edges.
    for i in range(NOISE):
        belief(agents[i % AGENTS], f"unrelated clean operational note {i}", source_id=good)
    seed_ms = int((time.perf_counter() - t_seed) * 1000)
    total = len(tainted) + NOISE
    print(f"seeded {total} beliefs in {seed_ms}ms ({int(total / max(seed_ms, 1) * 1000)}/s)")

    # The one recant.
    t0 = time.perf_counter()
    r = q.post("/recant", json={"source_id": bad, "actor": "scale"})
    recant_ms = int((time.perf_counter() - t0) * 1000)
    assert r.status_code == 200, r.text
    body = r.json()
    primitive = r.headers.get("X-Recant-Primitive", "")

    closure = len(body["closure_ids"])
    flipped = body["belief_count"]
    print(
        f"recant: closure={closure} flipped={flipped} agents={len(body['agent_ids'])}"
        f" latency={recant_ms}ms  [{primitive}]"
    )

    # Correctness at scale: the closure is exactly the contamination tree, every
    # tainted belief is quarantined, and not one clean belief moved.
    assert closure == len(tainted), f"closure {closure} != tainted {len(tainted)}"
    quarantined, clean = run_txn(
        lambda c: (
            c.execute("SELECT count(*) FROM beliefs WHERE status = 'quarantined'").fetchone()[0],
            c.execute("SELECT count(*) FROM beliefs WHERE status = 'active'").fetchone()[0],
        )
    )
    assert quarantined == len(tainted), f"quarantined {quarantined} != tainted {len(tainted)}"
    assert clean == NOISE, f"clean {clean} != noise {NOISE} (noise was touched)"

    # The recant is idempotent: a second call flips nothing new.
    again = q.post("/recant", json={"source_id": bad, "actor": "scale"}).json()
    assert again["belief_count"] == 0, f"second recant flipped {again['belief_count']}"

    print(
        f"PASS: {len(tainted)} tainted quarantined in one transaction, "
        f"{NOISE} clean untouched, repeat recant flipped 0"
    )


if __name__ == "__main__":
    main()

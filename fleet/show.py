"""Show an agent's assembled context: retrieved working memory plus recent
transcript turns, with belief ids and custody status. This is the before/after
surface for demo-visible eviction (proof moment 4): run it, recant, run the
worker, run it again; the paraphrase is present the first time and gone the
second, while clean beliefs persist.

Usage: python -m fleet.show --agent support [--query "refund policy"]
"""

from __future__ import annotations

import argparse
import os
from uuid import UUID

import psycopg

from fleet.bootstrap import history_for, store_for
from services.common.embedder import HashEmbedder  # noqa: F401  (query embeds via the store)

DEFAULT_QUERY = "refund policy window"
CONTEXT_K = 5
TRANSCRIPT_TURNS = 6


def assemble_context(agent_name: str, query: str) -> dict:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute("SELECT agent_id FROM agents WHERE name = %s", (agent_name,)).fetchone()
        if row is None:
            raise SystemExit(f"unknown agent {agent_name!r}: run the fleet first")
        agent_id: UUID = row[0]

        docs = store_for(agent_id).similarity_search(query, k=CONTEXT_K)
        statuses = {}
        if docs:
            ids = [UUID(d.id) for d in docs]
            statuses = dict(
                conn.execute(
                    "SELECT belief_id, status FROM beliefs WHERE belief_id = ANY(%s)", (ids,)
                ).fetchall()
            )

    turns = history_for(agent_name).messages[-TRANSCRIPT_TURNS:]
    return {
        "agent_id": agent_id,
        "memory": [
            {
                "belief_id": d.id,
                "content": d.page_content,
                "status": str(statuses.get(UUID(d.id), "MISSING FROM CUSTODY")),
            }
            for d in docs
        ],
        "transcript": [f"{m.type}: {m.content}" for m in turns],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Print an agent's assembled context")
    parser.add_argument("--agent", required=True, choices=["researcher", "support", "ops"])
    parser.add_argument("--query", default=DEFAULT_QUERY)
    args = parser.parse_args()

    ctx = assemble_context(args.agent, args.query)
    print(f"agent {args.agent} ({ctx['agent_id']}) context for query {args.query!r}:")
    if not ctx["memory"]:
        print("  working memory: (empty)")
    for m in ctx["memory"]:
        print(f"  [{m['status']:<12}] {m['belief_id']}  {m['content']}")
    print("recent transcript:")
    for t in ctx["transcript"]:
        print(f"  {t}")


if __name__ == "__main__":
    main()

"""Investigator: an agent that answers forensic questions about the memory by
querying CockroachDB read-only.

This is the agentic use of the CockroachDB Cloud Managed MCP Server: a Bedrock
Claude agent is given exactly one tool, ``query_memory`` (read-only SQL over the
cluster, the MCP server's core surface), and it decides which queries to run to
answer a natural-language question such as "is the ops bot's refund action
clean?" or "show the custody chain for belief X" or "which agents are affected
by incident Y". It never mutates the memory, and every query it runs is
audit-logged (ReadOnlySQL) and returned in the transcript, so you can see
exactly what the agent did with the tool.

    uv run python -m agent.investigator "is the ops bot's refund action clean?"

Bedrock credentials are required to run live; the tool-use loop is unit-tested
with fakes. Model defaults to the us.anthropic.claude-haiku-4-5 inference
profile (RECANT_INVESTIGATOR_MODEL overrides).
"""

from __future__ import annotations

import json
import os
import sys

from agent.readonly_sql import ReadOnlySQL, UnsafeQuery
from services.common.logging import configure

log = configure("agent.investigator")

DEFAULT_MODEL = os.environ.get(
    "RECANT_INVESTIGATOR_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
MAX_STEPS = 8

# The agent is told the schema so it writes correct queries without guessing.
_SYSTEM = """You are the Recant Investigator, a forensic analyst for an agent
memory system stored in CockroachDB. Answer the user's question by reading the
database with the query_memory tool. You may only read; you cannot change
anything.

Schema (read these columns; never SELECT embedding, sig, hash, or prev_hash,
they are huge or opaque):
  agents(agent_id, name, region, head_seq)
  sources(source_id, kind, uri, trust_tier)          trust_tier: verified|partner|public|untrusted
  beliefs(belief_id, agent_id, seq, content, status, source_id, created_at)
                                                     status: active|suspect|quarantined|retracted
  derivations(child_id, parent_id, kind, score)      kind: explicit|inferred (vector-inferred)
  incidents(incident_id, source_id, opened_by, created_at)
  quarantine_actions(action_id, incident_id, belief_count, actor, created_at)
  memory_events(event_id, kind, incident_id, payload, created_at)

Guidance:
- A belief is compromised if its status is 'suspect' or 'quarantined', or if it
  descends (via derivations, explicit or inferred) from a belief that cites a
  source with an open incident. A belief is clean if it is 'active' and no
  ancestor is compromised.
- To trace custody, walk derivations from the belief to its ancestors (where it
  came from) and descendants (where it spread). Use a recursive CTE.
- Prefer one focused query at a time. Keep results small (SELECT only the
  columns you need, add LIMIT). Reference specific belief_id / agent_id values
  in your answer. Be concise and factual; do not speculate beyond the rows.
When you have enough evidence, give a short plain-language answer."""

_TOOL = {
    "toolSpec": {
        "name": "query_memory",
        "description": (
            "Run one read-only SQL query against the CockroachDB memory store and "
            "return the rows. Read-only: SELECT/WITH/SHOW/EXPLAIN only, one statement."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "A single read-only SQL query."}
                },
                "required": ["sql"],
            }
        },
    }
}


class Investigator:
    def __init__(self, *, sql: ReadOnlySQL | None = None, client=None, model_id: str | None = None):
        self.sql = sql or ReadOnlySQL()
        self._client = client
        self.model_id = model_id or DEFAULT_MODEL

    def _bedrock(self):
        if self._client is None:
            import boto3

            region = (
                os.environ.get("AWS_REGION")
                or os.environ.get("AWS_DEFAULT_REGION")
                or "us-east-1"
            )
            self._client = boto3.client("bedrock-runtime", region_name=region)
        return self._client

    def _run_tool(self, tool_use: dict) -> dict:
        """Execute one query_memory call; return a Bedrock toolResult block."""
        tuid = tool_use["toolUseId"]
        sql = (tool_use.get("input") or {}).get("sql", "")
        try:
            result = self.sql.run(sql)
            body = {"json": result}
            status = "success"
        except UnsafeQuery as exc:
            body = {"json": {"error": f"rejected: {exc}"}}
            status = "error"
        except Exception as exc:  # a bad query: hand the error back so the model can fix it
            body = {"json": {"error": str(exc)[:300]}}
            status = "error"
        return {"toolResult": {"toolUseId": tuid, "content": [body], "status": status}}

    def ask(self, question: str) -> dict:
        """Answer a forensic question. Returns {answer, queries, steps}."""
        messages: list[dict] = [{"role": "user", "content": [{"text": question}]}]
        queries: list[str] = []

        for _ in range(MAX_STEPS):
            resp = self._bedrock().converse(
                modelId=self.model_id,
                system=[{"text": _SYSTEM}],
                messages=messages,
                toolConfig={"tools": [_TOOL]},
                inferenceConfig={"maxTokens": 1024, "temperature": 0},
            )
            out = resp["output"]["message"]
            messages.append(out)  # keep the assistant turn in the history

            tool_uses = [c["toolUse"] for c in out["content"] if "toolUse" in c]
            if not tool_uses:
                text = " ".join(c["text"] for c in out["content"] if "text" in c).strip()
                return {"answer": text, "queries": queries, "steps": len(queries)}

            results = []
            for tu in tool_uses:
                sql = (tu.get("input") or {}).get("sql", "")
                if sql:
                    queries.append(sql)
                results.append(self._run_tool(tu))
            messages.append({"role": "user", "content": results})

        return {
            "answer": "Investigation did not converge within the step budget.",
            "queries": queries,
            "steps": len(queries),
        }


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python -m agent.investigator "your forensic question"', file=sys.stderr)
        raise SystemExit(2)
    question = " ".join(sys.argv[1:])
    result = Investigator().ask(question)
    print(result["answer"])
    if result["queries"]:
        print("\n--- queries the agent ran (read-only, audit-logged) ---")
        for q in result["queries"]:
            print("  " + " ".join(q.split()))


if __name__ == "__main__":
    main()

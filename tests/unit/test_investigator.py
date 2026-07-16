"""The Investigator's tool-use loop: it runs the model's read-only queries, feeds
results back, returns the final answer, recovers from a rejected query, and stops
at the step budget. Bedrock and the SQL tool are fakes, so no AWS and no DB."""

import pytest

from agent.investigator import MAX_STEPS, Investigator
from agent.readonly_sql import UnsafeQuery


def _tool_use(sql, tuid="t1"):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": tuid, "name": "query_memory", "input": {"sql": sql}}}],
            }
        },
        "stopReason": "tool_use",
    }


def _final(text):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
    }


class _FakeBedrock:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def converse(self, **kw):
        # deepcopy: ask() mutates the same messages list in place, so snapshot
        # the state at call time instead of aliasing the final state.
        import copy

        self.calls.append(copy.deepcopy(kw))
        return copy.deepcopy(self.script[len(self.calls) - 1])


class _FakeSQL:
    def __init__(self, result=None, raises=None):
        self.result = result or {"columns": ["status"], "rows": [{"status": "quarantined"}], "truncated": False}
        self.raises = raises
        self.queries = []

    def run(self, sql):
        self.queries.append(sql)
        if self.raises:
            raise self.raises
        return self.result


def test_runs_query_then_answers():
    fake = _FakeBedrock([_tool_use("SELECT status FROM beliefs LIMIT 1"), _final("The belief is quarantined.")])
    sql = _FakeSQL()
    result = Investigator(sql=sql, client=fake).ask("is this belief clean?")
    assert result["answer"] == "The belief is quarantined."
    assert result["queries"] == ["SELECT status FROM beliefs LIMIT 1"]
    assert sql.queries == ["SELECT status FROM beliefs LIMIT 1"]
    # The tool result was fed back as a user turn before the final answer.
    second_call_messages = fake.calls[1]["messages"]
    assert any(
        "toolResult" in block
        for m in second_call_messages
        for block in (m["content"] if isinstance(m["content"], list) else [])
    )


def test_recovers_from_rejected_query():
    fake = _FakeBedrock([_tool_use("DELETE FROM beliefs"), _final("I can only read; here is what I found.")])
    sql = _FakeSQL(raises=UnsafeQuery("only read-only queries are allowed"))
    result = Investigator(sql=sql, client=fake).ask("delete everything")
    assert result["answer"].startswith("I can only read")
    # The rejection was returned to the model as an error toolResult.
    tool_result = fake.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert tool_result["status"] == "error"
    assert "rejected" in tool_result["content"][0]["json"]["error"]


def test_stops_at_step_budget():
    # The model never stops calling the tool; the agent must bail out.
    fake = _FakeBedrock([_tool_use(f"SELECT {i}") for i in range(MAX_STEPS + 2)])
    result = Investigator(sql=_FakeSQL(), client=fake).ask("loop forever")
    assert "did not converge" in result["answer"]
    assert len(result["queries"]) == MAX_STEPS


def test_forwards_model_and_temperature_zero():
    fake = _FakeBedrock([_final("done")])
    Investigator(sql=_FakeSQL(), client=fake, model_id="us.anthropic.claude-sonnet-5").ask("hi")
    call = fake.calls[0]
    assert call["modelId"] == "us.anthropic.claude-sonnet-5"
    assert call["inferenceConfig"]["temperature"] == 0
    assert call["toolConfig"]["tools"][0]["toolSpec"]["name"] == "query_memory"

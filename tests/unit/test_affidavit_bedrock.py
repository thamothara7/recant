"""The Bedrock affidavit generator must send the structured facts verbatim at
temperature 0, return only real affidavits, and the dispatcher must fall back
to the deterministic template on any Bedrock failure so the judge-facing
endpoint keeps answering. No test touches AWS: clients are injected fakes."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.forensics.affidavit import (
    DEFAULT_MODEL,
    BedrockAffidavitGenerator,
    generate_affidavit,
)


def _structured() -> dict:
    return {
        "incident_id": uuid4(),
        "created_at": datetime(2026, 7, 16, 14, 32, 0, tzinfo=timezone.utc),
        "opened_by": "operator",
        "source_id": uuid4(),
        "source_kind": "web_scrape",
        "source_uri": "https://forum.example.com/thread/4471",
        "source_trust_tier": "untrusted",
        "belief_count": 3,
        "agents_affected": [{"agent_name": "researcher", "belief_count": 3}],
        "actions": [{
            "action_id": str(uuid4()),
            "sig": "ab" * 32,
            "sig_status": "valid",
            "belief_count": 3,
        }],
        "events": [],
    }


class _FakeConverse:
    def __init__(self, text="INCIDENT AFFIDAVIT\nAll facts stated.", error=None):
        self.text = text
        self.error = error
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"output": {"message": {"content": [{"text": self.text}]}}}


def test_generate_sends_facts_at_temperature_zero():
    fake = _FakeConverse()
    structured = _structured()
    gen = BedrockAffidavitGenerator(client=fake)
    text = gen.generate(structured)
    assert "INCIDENT AFFIDAVIT" in text
    (call,) = fake.calls
    assert call["modelId"] == DEFAULT_MODEL
    assert call["inferenceConfig"] == {"maxTokens": 1024, "temperature": 0}
    assert "forensic scribe" in call["system"][0]["text"]
    prompt = call["messages"][0]["content"][0]["text"]
    assert str(structured["incident_id"]) in prompt
    assert "forum.example.com/thread/4471" in prompt


def test_generate_rejects_non_affidavit_response():
    gen = BedrockAffidavitGenerator(client=_FakeConverse(text="I cannot help."))
    with pytest.raises(ValueError, match="not an affidavit"):
        gen.generate(_structured())


def test_construction_and_selection_never_touch_aws(monkeypatch):
    monkeypatch.setenv("RECANT_AFFIDAVIT", "bedrock")
    gen = BedrockAffidavitGenerator()
    assert gen._client is None


def test_dispatcher_defaults_to_template(monkeypatch):
    monkeypatch.delenv("RECANT_AFFIDAVIT", raising=False)
    text, generated_by = generate_affidavit(_structured())
    assert generated_by == "template"
    assert "generated from database records using a text template" in text


def test_dispatcher_bedrock_mode_reports_model_id(monkeypatch):
    monkeypatch.setenv("RECANT_AFFIDAVIT", "bedrock")
    text, generated_by = generate_affidavit(
        _structured(), bedrock_client=_FakeConverse()
    )
    assert generated_by == DEFAULT_MODEL
    assert text.startswith("INCIDENT AFFIDAVIT")


def test_dispatcher_falls_back_to_template_on_bedrock_error(monkeypatch):
    monkeypatch.setenv("RECANT_AFFIDAVIT", "bedrock")
    text, generated_by = generate_affidavit(
        _structured(), bedrock_client=_FakeConverse(error=RuntimeError("throttled"))
    )
    assert generated_by == "template (bedrock error)"
    assert "INCIDENT AFFIDAVIT" in text


def test_dispatcher_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("RECANT_AFFIDAVIT", "nonsense")
    with pytest.raises(ValueError, match="unknown RECANT_AFFIDAVIT"):
        generate_affidavit(_structured())


def test_model_id_env_override(monkeypatch):
    monkeypatch.setenv("RECANT_AFFIDAVIT_MODEL", "anthropic.claude-sonnet-5")
    fake = _FakeConverse()
    BedrockAffidavitGenerator(client=fake).generate(_structured())
    assert fake.calls[0]["modelId"] == "anthropic.claude-sonnet-5"

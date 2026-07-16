"""The EventBridge consumer must round-trip exactly what the receiver emits,
reject contract violations loudly, and resolve its database URL from env
first, SSM second, cached per container. No AWS, no DB: fakes only."""

import json
from uuid import uuid4

import pytest

import fanout.consumer_entry as consumer_entry
from fanout.consumer_entry import _database_url, detail_to_event
from fanout.handler import Eviction, MalformedEvent, RecantEvent
from fanout.lambda_entry import to_entries


def _event() -> RecantEvent:
    return RecantEvent(
        event_id=uuid4(),
        incident_id=uuid4(),
        source_id=uuid4(),
        actor="operator",
        evictions=(
            Eviction(agent_id=uuid4(), belief_ids=(uuid4(), uuid4())),
            Eviction(agent_id=uuid4(), belief_ids=()),
        ),
    )


def test_detail_round_trips_receiver_entries():
    original = _event()
    (entry,) = to_entries([original], bus_name="recant")
    detail = json.loads(entry["Detail"])
    rebuilt = detail_to_event(detail)
    assert rebuilt == original


def test_detail_missing_ids_is_malformed():
    with pytest.raises(MalformedEvent, match="missing ids"):
        detail_to_event({"actor": "x"})


def test_detail_contract_violation_is_malformed():
    original = _event()
    (entry,) = to_entries([original], bus_name="recant")
    detail = json.loads(entry["Detail"])
    detail["evictions"] = "not-a-list"
    with pytest.raises(MalformedEvent):
        detail_to_event(detail)


class _FakeSSM:
    def __init__(self, value="postgresql://ssm"):
        self.value = value
        self.calls: list[str] = []

    def get_parameter(self, Name, WithDecryption):
        assert WithDecryption is True
        self.calls.append(Name)
        return {"Parameter": {"Value": self.value}}


def test_database_url_env_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://env")
    fake = _FakeSSM()
    assert _database_url(ssm_client=fake) == "postgresql://env"
    assert fake.calls == []


def test_database_url_from_ssm_cached(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("RECANT_DB_PARAM", "/recant/test_param")
    monkeypatch.setattr(consumer_entry, "_cached_url", None)
    fake = _FakeSSM()
    assert _database_url(ssm_client=fake) == "postgresql://ssm"
    assert _database_url(ssm_client=fake) == "postgresql://ssm"
    assert fake.calls == ["/recant/test_param"]  # second call served from cache
    monkeypatch.setattr(consumer_entry, "_cached_url", None)

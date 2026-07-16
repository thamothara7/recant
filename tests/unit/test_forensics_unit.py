"""Unit tests for the forensics affidavit text template."""

from datetime import datetime, timezone
from uuid import uuid4

from services.forensics.app import generate_affidavit_text


def test_normal_affidavit():
    text = generate_affidavit_text(
        incident_id=uuid4(),
        created_at=datetime(2026, 7, 12, 14, 32, 0, tzinfo=timezone.utc),
        opened_by="operator",
        source_id=uuid4(),
        source_kind="web_scrape",
        source_uri="https://forum.example.com/thread/4471",
        source_trust_tier="untrusted",
        belief_count=3,
        agents_affected=[
            {"agent_name": "researcher", "belief_count": 1},
            {"agent_name": "support", "belief_count": 2},
        ],
        actions=[{
            "action_id": str(uuid4()),
            "sig": "ab" * 32,
            "sig_status": "valid",
            "belief_count": 3,
        }],
        events=[{
            "created_at": datetime(2026, 7, 12, 14, 32, 1, tzinfo=timezone.utc),
            "kind": "recant",
            "summary": "3 beliefs quarantined",
        }],
    )
    assert "INCIDENT AFFIDAVIT" in text
    assert "3 belief(s) quarantined across 2 agent(s)" in text
    assert "forum.example.com" in text
    assert "researcher" in text
    assert "support" in text
    assert "untrusted" in text
    assert "valid" in text
    assert "generated from database records using a text template" in text


def test_zero_closure_affidavit():
    text = generate_affidavit_text(
        incident_id=uuid4(),
        created_at=datetime(2026, 7, 12, 0, 0, 0, tzinfo=timezone.utc),
        opened_by="system",
        source_id=uuid4(),
        source_kind="api",
        source_uri="https://api.example.com/v1/data",
        source_trust_tier="public",
        belief_count=0,
        agents_affected=[],
        actions=[],
        events=[],
    )
    assert "0 belief(s) quarantined across 0 agent(s)" in text
    assert "(none recorded)" in text
    assert "(no events recorded)" in text


def test_large_count_affidavit():
    agents = [{"agent_name": f"agent_{i}", "belief_count": 10} for i in range(10)]
    text = generate_affidavit_text(
        incident_id=uuid4(),
        created_at=datetime(2026, 7, 12, 0, 0, 0, tzinfo=timezone.utc),
        opened_by="admin",
        source_id=uuid4(),
        source_kind="feed",
        source_uri="https://feed.example.com/rss",
        source_trust_tier="partner",
        belief_count=100,
        agents_affected=agents,
        actions=[],
        events=[],
    )
    assert "100 belief(s) quarantined across 10 agent(s)" in text
    assert "agent_9" in text


def test_all_fields_present():
    iid = uuid4()
    sid = uuid4()
    text = generate_affidavit_text(
        incident_id=iid,
        created_at=datetime(2026, 7, 12, 10, 0, 0, tzinfo=timezone.utc),
        opened_by="tester",
        source_id=sid,
        source_kind="manual",
        source_uri="urn:test:source",
        source_trust_tier="verified",
        belief_count=1,
        agents_affected=[{"agent_name": "bot", "belief_count": 1}],
        actions=[],
        events=[],
    )
    assert str(iid) in text
    assert str(sid) in text
    assert "tester" in text
    assert "urn:test:source" in text
    assert "verified" in text
    assert "manual" in text

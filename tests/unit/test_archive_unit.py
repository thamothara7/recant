"""The S3 archiver must write deterministic keys under one incident prefix,
send the right content types, surface a missing bucket loudly, and never
touch AWS on import or construction. Clients are injected fakes."""

from uuid import uuid4

import pytest

from services.forensics.archive import MissingBucket, S3EvidenceArchiver


class _FakeS3:
    def __init__(self):
        self.puts: list[dict] = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {"ETag": '"abc"'}


def test_put_bundle_writes_deterministic_keys():
    fake = _FakeS3()
    iid = uuid4()
    archiver = S3EvidenceArchiver(client=fake, bucket="evidence-test")
    keys = archiver.put_bundle(
        iid,
        {
            "incident.json": ('{"a": 1}', "application/json"),
            "affidavit.txt": ("INCIDENT AFFIDAVIT", "text/plain; charset=utf-8"),
            "custody/agent-1.json": ("{}", "application/json"),
        },
    )
    assert keys == [
        f"incidents/{iid}/incident.json",
        f"incidents/{iid}/affidavit.txt",
        f"incidents/{iid}/custody/agent-1.json",
    ]
    assert [p["Bucket"] for p in fake.puts] == ["evidence-test"] * 3
    by_key = {p["Key"]: p for p in fake.puts}
    aff = by_key[f"incidents/{iid}/affidavit.txt"]
    assert aff["Body"] == b"INCIDENT AFFIDAVIT"
    assert aff["ContentType"] == "text/plain; charset=utf-8"
    assert by_key[f"incidents/{iid}/incident.json"]["ContentType"] == "application/json"


def test_missing_bucket_is_loud(monkeypatch):
    monkeypatch.delenv("RECANT_EVIDENCE_BUCKET", raising=False)
    archiver = S3EvidenceArchiver(client=_FakeS3())
    with pytest.raises(MissingBucket, match="RECANT_EVIDENCE_BUCKET"):
        archiver.put_bundle(uuid4(), {"incident.json": ("{}", "application/json")})


def test_bucket_from_env(monkeypatch):
    monkeypatch.setenv("RECANT_EVIDENCE_BUCKET", "from-env")
    assert S3EvidenceArchiver(client=_FakeS3()).bucket == "from-env"


def test_construction_does_not_touch_aws():
    archiver = S3EvidenceArchiver()
    assert archiver._client is None

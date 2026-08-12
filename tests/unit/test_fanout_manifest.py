import hashlib
import json
from io import BytesIO
from uuid import uuid4

import pytest

import fanout.lambda_entry as receiver
from fanout.consumer_entry import _resolve_manifest
from fanout.handler import Eviction, MalformedEvent, RecantEvent


class _FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = bytes(kwargs["Body"])

    def get_object(self, *, Bucket, Key):
        body = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body), "Body": BytesIO(body)}


def _event() -> RecantEvent:
    return RecantEvent(
        event_id=uuid4(),
        incident_id=uuid4(),
        source_id=uuid4(),
        actor="operator",
        evictions=(Eviction(agent_id=uuid4(), belief_ids=(uuid4(), uuid4())),),
    )


def test_oversized_event_uses_digest_checked_s3_manifest(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setenv("RECANT_EVENT_MANIFEST_BUCKET", "manifest-bucket")
    monkeypatch.setattr(receiver, "MAX_ENTRY_BYTES", 1)
    event = _event()
    (entry,) = receiver.to_entries([event], bus_name="recant", manifest_client=fake)
    pointer = json.loads(entry["Detail"])
    hydrated = _resolve_manifest(pointer, s3_client=fake)
    assert hydrated["event_id"] == str(event.event_id)
    assert hydrated["tenant_id"] == str(event.tenant_id)

    key = ("manifest-bucket", pointer["manifest"]["key"])
    fake.objects[key] += b"tamper"
    with pytest.raises(MalformedEvent, match="digest"):
        _resolve_manifest(pointer, s3_client=fake)


def test_manifest_bucket_and_key_are_pinned(monkeypatch):
    monkeypatch.setenv("RECANT_EVENT_MANIFEST_BUCKET", "allowed")
    detail = {
        "event_id": str(uuid4()),
        "manifest": {
            "bucket": "other",
            "key": "fanout/tenant/event.json",
            "sha256": hashlib.sha256(b"{}").hexdigest(),
        },
    }
    with pytest.raises(MalformedEvent, match="outside"):
        _resolve_manifest(detail, s3_client=_FakeS3())

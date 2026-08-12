from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

from services.forensics.checkpoint import (
    S3CheckpointPublisher,
    checkpoint_payload,
    custody_leaves,
    merkle_root,
)


def test_merkle_root_is_deterministic_across_agent_input_order():
    first, second = uuid4(), uuid4()
    rows = [(second, 2, b"b" * 32), (first, 1, b"a" * 32)]
    ordered = custody_leaves(rows)
    reversed_input = custody_leaves(list(reversed(rows)))
    assert ordered == reversed_input
    assert merkle_root(ordered) == merkle_root(reversed_input)
    assert merkle_root([]) != merkle_root(ordered)


def test_checkpoint_payload_binds_previous_root_and_leaves():
    tenant_id = uuid4()
    checkpoint_id = uuid4()
    leaves = custody_leaves([(uuid4(), 1, b"a" * 32)])
    root = merkle_root(leaves)
    payload = checkpoint_payload(
        checkpoint_id=checkpoint_id,
        tenant_id=tenant_id,
        root_hash=root,
        leaves=leaves,
        previous_root_hash=b"p" * 32,
        created_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert root.hex().encode() in payload
    assert (b"p" * 32).hex().encode() in payload


class _FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[(Bucket, Key)]["Body"])}


def test_checkpoint_publisher_encrypts_and_reads_configured_bucket(monkeypatch):
    monkeypatch.delenv("RECANT_OBJECT_LOCK_DAYS", raising=False)
    fake = _FakeS3()
    publisher = S3CheckpointPublisher(client=fake, bucket="checkpoint-bucket")
    tenant_id, checkpoint_id = uuid4(), uuid4()
    uri = publisher.publish(tenant_id, checkpoint_id, b"evidence")
    stored = fake.objects[("checkpoint-bucket", f"checkpoints/{tenant_id}/{checkpoint_id}.json")]
    assert stored["ServerSideEncryption"] == "AES256"
    assert publisher.read(uri) == b"evidence"

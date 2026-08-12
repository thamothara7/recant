"""Merkle checkpoints and optional immutable S3 publication."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from services.common.attestation import canonical_json, sha256


class MissingCheckpointBucket(RuntimeError):
    pass


def custody_leaves(rows: list[tuple]) -> list[dict[str, Any]]:
    leaves = []
    for agent_id, head_seq, head_hash in sorted(rows, key=lambda row: str(row[0])):
        leaves.append(
            {
                "agent_id": str(agent_id),
                "head_seq": int(head_seq),
                "head_hash": bytes(head_hash).hex() if head_hash is not None else None,
            }
        )
    return leaves


def merkle_root(leaves: list[dict[str, Any]]) -> bytes:
    level = [sha256(b"recant-leaf-v1\x00" + canonical_json(leaf)) for leaf in leaves]
    if not level:
        return sha256(b"recant-empty-tree-v1")
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            sha256(b"recant-node-v1\x00" + level[index] + level[index + 1])
            for index in range(0, len(level), 2)
        ]
    return level[0]


def checkpoint_payload(
    *,
    checkpoint_id: UUID,
    tenant_id: UUID,
    root_hash: bytes,
    leaves: list[dict[str, Any]],
    previous_root_hash: bytes | None,
    created_at: datetime,
) -> bytes:
    return canonical_json(
        {
            "type": "recant.custody-checkpoint.v1",
            "checkpoint_id": checkpoint_id,
            "tenant_id": tenant_id,
            "root_hash": root_hash.hex(),
            "leaf_count": len(leaves),
            "leaves": leaves,
            "previous_root_hash": previous_root_hash.hex() if previous_root_hash else None,
            "created_at": created_at,
        }
    )


class S3CheckpointPublisher:
    def __init__(self, client=None, bucket: str | None = None):
        self._client = client
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        value = self._bucket or os.environ.get("RECANT_CHECKPOINT_BUCKET")
        if not value:
            raise MissingCheckpointBucket(
                "RECANT_CHECKPOINT_BUCKET is not set; rollback detection needs an independent store"
            )
        return value

    def _s3(self):
        if self._client is None:  # pragma: no cover - exercised against AWS
            import boto3

            self._client = boto3.client(
                "s3",
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            )
        return self._client

    def publish(self, tenant_id: UUID, checkpoint_id: UUID, document: bytes) -> str:
        key = f"checkpoints/{tenant_id}/{checkpoint_id}.json"
        args: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": document,
            "ContentType": "application/json",
            "ServerSideEncryption": "AES256",
        }
        lock_days = int(os.environ.get("RECANT_OBJECT_LOCK_DAYS", "0"))
        if lock_days > 0:
            args.update(
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=datetime.now(timezone.utc) + timedelta(days=lock_days),
            )
        self._s3().put_object(**args)
        return f"s3://{self.bucket}/{key}"

    def read(self, uri: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("checkpoint URI points outside the configured bucket")
        key = uri[len(prefix) :]
        return self._s3().get_object(Bucket=self.bucket, Key=key)["Body"].read()


def published_document(
    *,
    payload: bytes,
    sig: bytes,
    pubkey: bytes,
    algorithm: str,
    key_id: str,
) -> bytes:
    return canonical_json(
        {
            "payload": json.loads(payload),
            "signature": sig.hex(),
            "public_key": pubkey.hex(),
            "signing_algorithm": algorithm,
            "signer_key_id": key_id,
        }
    )

"""Evidence archive: one incident's forensic bundle to S3 (W4, U3).

POST /incidents/{id}/archive assembles what a DB-less verifier needs: the
incident summary with per-action signature verdicts, the affidavit, and the
custody chain of every affected agent, and writes it to S3 under a
deterministic prefix. Keys are stable, so re-archiving overwrites the same
objects with refreshed content and the bucket's versioning keeps history.

The boto3 client is lazy and injectable, mirroring TitanEmbedder and the
Bedrock affidavit generator: importing and constructing never touch AWS.
"""

from __future__ import annotations

import os
from uuid import UUID


class MissingBucket(RuntimeError):
    """RECANT_EVIDENCE_BUCKET is not configured."""


class S3EvidenceArchiver:
    def __init__(self, client=None, bucket: str | None = None):
        self._client = client
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        bucket = self._bucket or os.environ.get("RECANT_EVIDENCE_BUCKET")
        if not bucket:
            raise MissingBucket(
                "RECANT_EVIDENCE_BUCKET is not set; the evidence archive has no destination"
            )
        return bucket

    def _s3(self):
        if self._client is None:
            import boto3

            region = (
                os.environ.get("AWS_REGION")
                or os.environ.get("AWS_DEFAULT_REGION")
                or "us-east-1"
            )
            self._client = boto3.client("s3", region_name=region)
        return self._client

    def put_bundle(self, incident_id: UUID, documents: dict[str, tuple[str, str]]) -> list[str]:
        """Write one incident's documents; returns the S3 keys written.

        documents maps a relative name to (body, content_type). Keys land
        under incidents/{incident_id}/ so one prefix is one incident's
        complete evidence bundle.
        """
        bucket = self.bucket
        s3 = self._s3()
        keys: list[str] = []
        for name, (body, content_type) in documents.items():
            key = f"incidents/{incident_id}/{name}"
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType=content_type,
            )
            keys.append(key)
        return keys

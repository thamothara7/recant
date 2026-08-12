-- Idempotent responses can contain one-use Guard permits. Keep those bearer
-- capabilities encrypted at rest while preserving exact response replay.

ALTER TABLE idempotency_records ADD COLUMN IF NOT EXISTS response_ciphertext BYTES;
ALTER TABLE idempotency_records ADD COLUMN IF NOT EXISTS response_nonce BYTES;
ALTER TABLE idempotency_records
    ADD COLUMN IF NOT EXISTS encryption_version STRING NOT NULL DEFAULT 'none';

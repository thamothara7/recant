-- New quarantine attestations bind the tenant and a payload type. Historical
-- rows remain verifiable with the byte-stable v1 format.

ALTER TABLE quarantine_actions
    ADD COLUMN IF NOT EXISTS attestation_version STRING NOT NULL DEFAULT 'v1';

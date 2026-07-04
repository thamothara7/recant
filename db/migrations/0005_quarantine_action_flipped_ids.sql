-- Make an attested quarantine action verifiable from the stored rows alone
-- (spec section 6). The signed payload binds sorted(newly_flipped_ids), but the
-- action row previously stored only belief_count; the id list survived only in
-- the unsigned memory_events outbox, which the W3 fanout consumes and prunes.
-- Persist the exact signed id list on the action itself so a forensics verifier
-- holding only the database can recompute the canonical payload and check the
-- signature (review 2026-07-03).
ALTER TABLE quarantine_actions ADD COLUMN IF NOT EXISTS newly_flipped_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[];

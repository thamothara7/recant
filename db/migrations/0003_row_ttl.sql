-- Row-level TTL for low-trust beliefs: rows with NULL ttl_expire_at never expire.
-- The gateway sets ttl_expire_at = created_at + 7 days when the source trust_tier
-- is 'untrusted'. gc.ttlseconds (AOST forensics window) is configured separately
-- in ops/chaos/configure-gc.sh because zone configs may be restricted on Cloud Basic.

ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS ttl_expire_at TIMESTAMPTZ;

ALTER TABLE beliefs SET (ttl_expiration_expression = 'ttl_expire_at');

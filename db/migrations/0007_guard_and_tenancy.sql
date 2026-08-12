-- Production security and Recant Guard.
--
-- Every existing row is assigned to the stable development tenant. New
-- production tenants are provisioned with ops/provision_tenant.py and receive
-- a dedicated SQL role used by the RLS policies at the bottom of this file.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   UUID PRIMARY KEY,
    slug        STRING NOT NULL UNIQUE,
    display_name STRING NOT NULL,
    active      BOOL NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO tenants (tenant_id, slug, display_name)
VALUES ('00000000-0000-0000-0000-000000000001', 'development', 'Development')
ON CONFLICT (tenant_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS api_principals (
    principal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants (tenant_id),
    subject      STRING NOT NULL,
    token_hash   BYTES NOT NULL UNIQUE,
    roles        STRING[] NOT NULL,
    active       BOOL NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, subject),
    INDEX api_principals_tenant_idx (tenant_id)
);

ALTER TABLE sources ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
ALTER TABLE sources ADD COLUMN IF NOT EXISTS authority_rank INT8 NOT NULL DEFAULT 10;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS issuer_principal_id UUID REFERENCES api_principals (principal_id);
ALTER TABLE sources ADD COLUMN IF NOT EXISTS issuer_subject STRING NOT NULL DEFAULT 'legacy';
ALTER TABLE sources ADD COLUMN IF NOT EXISTS assertion_sig BYTES;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS assertion_pubkey BYTES;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS signing_algorithm STRING;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS signer_key_id STRING;
CREATE INDEX IF NOT EXISTS sources_tenant_idx ON sources (tenant_id);

ALTER TABLE agents ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS signing_algorithm STRING NOT NULL DEFAULT 'ed25519';
ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_name_key;
ALTER TABLE agents ADD CONSTRAINT IF NOT EXISTS agents_tenant_name_key UNIQUE (tenant_id, name);
CREATE INDEX IF NOT EXISTS agents_tenant_idx ON agents (tenant_id);

ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS authority_rank INT8 NOT NULL DEFAULT 0;
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS origin_source_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[];
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS provenance_method STRING NOT NULL DEFAULT 'legacy';
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS provenance_version STRING NOT NULL DEFAULT 'v1';
CREATE INDEX IF NOT EXISTS beliefs_tenant_idx ON beliefs (tenant_id);

ALTER TABLE derivations ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
ALTER TABLE derivations ADD COLUMN IF NOT EXISTS evidence_method STRING NOT NULL DEFAULT 'declared';
ALTER TABLE derivations ADD COLUMN IF NOT EXISTS evidence_model STRING;
ALTER TABLE derivations ADD COLUMN IF NOT EXISTS evidence_version STRING NOT NULL DEFAULT 'v1';
CREATE INDEX IF NOT EXISTS derivations_tenant_idx ON derivations (tenant_id);

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
CREATE INDEX IF NOT EXISTS incidents_tenant_idx ON incidents (tenant_id);

ALTER TABLE quarantine_actions ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
ALTER TABLE quarantine_actions ADD COLUMN IF NOT EXISTS signer_pubkey BYTES;
ALTER TABLE quarantine_actions ADD COLUMN IF NOT EXISTS signing_algorithm STRING;
ALTER TABLE quarantine_actions ADD COLUMN IF NOT EXISTS signer_key_id STRING;
CREATE INDEX IF NOT EXISTS quarantine_actions_tenant_idx ON quarantine_actions (tenant_id);

ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
CREATE INDEX IF NOT EXISTS memory_events_tenant_idx ON memory_events (tenant_id);

ALTER TABLE fanout_deliveries ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
CREATE INDEX IF NOT EXISTS fanout_deliveries_tenant_idx ON fanout_deliveries (tenant_id);

ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001' REFERENCES tenants (tenant_id);
ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS decision_id UUID;
ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS permit_id UUID;
CREATE INDEX IF NOT EXISTS agent_actions_tenant_idx ON agent_actions (tenant_id);
CREATE INVERTED INDEX IF NOT EXISTS agent_actions_derived_from_idx ON agent_actions (derived_from);

CREATE TABLE IF NOT EXISTS context_receipts (
    receipt_id        UUID PRIMARY KEY,
    tenant_id         UUID NOT NULL REFERENCES tenants (tenant_id),
    agent_id          UUID NOT NULL REFERENCES agents (agent_id),
    issued_to         UUID REFERENCES api_principals (principal_id),
    belief_ids        UUID[] NOT NULL,
    belief_hashes     STRING[] NOT NULL,
    origin_source_ids UUID[] NOT NULL,
    authority_rank    INT8 NOT NULL,
    payload_hash      BYTES NOT NULL,
    sig               BYTES NOT NULL,
    signer_pubkey     BYTES NOT NULL,
    signing_algorithm STRING NOT NULL,
    signer_key_id     STRING NOT NULL,
    expires_at        TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX context_receipts_tenant_idx (tenant_id),
    INDEX context_receipts_agent_idx (agent_id)
);

CREATE TABLE IF NOT EXISTS tool_policies (
    tenant_id             UUID NOT NULL REFERENCES tenants (tenant_id),
    tool_name             STRING NOT NULL,
    risk_class            STRING NOT NULL CHECK (risk_class IN ('read', 'navigate', 'effect', 'purchase', 'credential')),
    required_authority    INT8 NOT NULL,
    confirmation_allowed  BOOL NOT NULL DEFAULT true,
    policy_version        STRING NOT NULL,
    updated_by            UUID REFERENCES api_principals (principal_id),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, tool_name)
);

CREATE TABLE IF NOT EXISTS action_decisions (
    decision_id        UUID PRIMARY KEY,
    tenant_id          UUID NOT NULL REFERENCES tenants (tenant_id),
    agent_id           UUID NOT NULL REFERENCES agents (agent_id),
    requested_by       UUID REFERENCES api_principals (principal_id),
    tool_name          STRING NOT NULL,
    arguments          JSONB NOT NULL,
    action_digest      BYTES NOT NULL,
    support_belief_ids UUID[] NOT NULL,
    context_receipt_id UUID REFERENCES context_receipts (receipt_id),
    supersedes_decision_id UUID REFERENCES action_decisions (decision_id),
    risk_class         STRING NOT NULL,
    required_authority INT8 NOT NULL,
    observed_authority INT8 NOT NULL,
    decision           STRING NOT NULL CHECK (decision IN ('allow', 'confirm', 'deny')),
    reason             STRING NOT NULL,
    policy_version     STRING NOT NULL,
    sig                BYTES NOT NULL,
    signer_pubkey      BYTES NOT NULL,
    signing_algorithm  STRING NOT NULL,
    signer_key_id      STRING NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX action_decisions_tenant_idx (tenant_id),
    INDEX action_decisions_agent_idx (agent_id),
    INDEX action_decisions_decision_idx (decision)
);

CREATE INVERTED INDEX IF NOT EXISTS action_decisions_support_idx ON action_decisions (support_belief_ids);

CREATE TABLE IF NOT EXISTS action_confirmations (
    confirmation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants (tenant_id),
    decision_id     UUID NOT NULL UNIQUE REFERENCES action_decisions (decision_id),
    confirmed_by    UUID REFERENCES api_principals (principal_id),
    subject         STRING NOT NULL,
    reason          STRING NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX action_confirmations_tenant_idx (tenant_id)
);

CREATE TABLE IF NOT EXISTS action_permits (
    permit_id          UUID PRIMARY KEY,
    tenant_id          UUID NOT NULL REFERENCES tenants (tenant_id),
    decision_id        UUID NOT NULL UNIQUE REFERENCES action_decisions (decision_id),
    token_hash         BYTES NOT NULL UNIQUE,
    action_digest      BYTES NOT NULL,
    nonce              UUID NOT NULL,
    signer_pubkey      BYTES NOT NULL,
    signing_algorithm  STRING NOT NULL,
    signer_key_id      STRING NOT NULL,
    expires_at         TIMESTAMPTZ NOT NULL,
    consumed_at        TIMESTAMPTZ,
    revoked_at         TIMESTAMPTZ,
    revoke_reason      STRING,
    incident_id        UUID REFERENCES incidents (incident_id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX action_permits_tenant_idx (tenant_id),
    INDEX action_permits_expiry_idx (expires_at)
);

CREATE TABLE IF NOT EXISTS semantic_relations (
    tenant_id        UUID NOT NULL REFERENCES tenants (tenant_id),
    left_belief_id   UUID NOT NULL REFERENCES beliefs (belief_id),
    right_belief_id  UUID NOT NULL REFERENCES beliefs (belief_id),
    relation         STRING NOT NULL CHECK (relation IN ('equivalent', 'entails', 'contradicts', 'related', 'unknown')),
    confidence       FLOAT8 NOT NULL,
    evidence_method  STRING NOT NULL,
    evidence_model   STRING,
    evidence_version STRING NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, left_belief_id, right_belief_id)
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    tenant_id      UUID NOT NULL REFERENCES tenants (tenant_id),
    principal_key  STRING NOT NULL,
    method         STRING NOT NULL,
    path           STRING NOT NULL,
    idempotency_key STRING NOT NULL,
    request_hash   BYTES NOT NULL,
    response_status INT8 NOT NULL,
    response_body  JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, principal_key, method, path, idempotency_key)
);

ALTER TABLE idempotency_records SET (ttl_expiration_expression = 'expires_at');

CREATE TABLE IF NOT EXISTS custody_checkpoints (
    checkpoint_id     UUID PRIMARY KEY,
    tenant_id         UUID NOT NULL REFERENCES tenants (tenant_id),
    root_hash         BYTES NOT NULL,
    leaf_count        INT8 NOT NULL,
    leaves            JSONB NOT NULL,
    previous_root_hash BYTES,
    sig               BYTES NOT NULL,
    signer_pubkey     BYTES NOT NULL,
    signing_algorithm STRING NOT NULL,
    signer_key_id     STRING NOT NULL,
    external_uri      STRING,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX custody_checkpoints_tenant_idx (tenant_id, created_at DESC)
);

ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE beliefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE derivations ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE quarantine_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE fanout_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE context_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_confirmations ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_permits ENABLE ROW LEVEL SECURITY;
ALTER TABLE semantic_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE custody_checkpoints ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS sources_tenant_policy ON sources FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS agents_tenant_policy ON agents FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS beliefs_tenant_policy ON beliefs FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS derivations_tenant_policy ON derivations FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS incidents_tenant_policy ON incidents FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS quarantine_actions_tenant_policy ON quarantine_actions FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS memory_events_tenant_policy ON memory_events FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS fanout_deliveries_tenant_policy ON fanout_deliveries FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS agent_actions_tenant_policy ON agent_actions FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS context_receipts_tenant_policy ON context_receipts FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS tool_policies_tenant_policy ON tool_policies FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS action_decisions_tenant_policy ON action_decisions FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS action_confirmations_tenant_policy ON action_confirmations FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS action_permits_tenant_policy ON action_permits FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS semantic_relations_tenant_policy ON semantic_relations FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS idempotency_records_tenant_policy ON idempotency_records FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));
CREATE POLICY IF NOT EXISTS custody_checkpoints_tenant_policy ON custody_checkpoints FOR ALL TO PUBLIC USING (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', '')) WITH CHECK (current_user() = 'recant_t_' || replace(tenant_id::STRING, '-', ''));

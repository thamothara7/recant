-- Recant core schema (spec sections 5 and 6). CockroachDB is the only store.

CREATE TYPE IF NOT EXISTS belief_status AS ENUM ('active', 'suspect', 'quarantined', 'retracted');

CREATE TYPE IF NOT EXISTS derivation_kind AS ENUM ('explicit', 'inferred');

CREATE TABLE IF NOT EXISTS sources (
    source_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind       STRING NOT NULL,
    uri        STRING NOT NULL,
    trust_tier STRING NOT NULL CHECK (trust_tier IN ('verified', 'partner', 'public', 'untrusted')),
    region     STRING NOT NULL DEFAULT 'local',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        STRING NOT NULL UNIQUE,
    pubkey      BYTES NOT NULL,
    kms_key_arn STRING,
    head_hash   BYTES,
    head_seq    INT8 NOT NULL DEFAULT 0,
    region      STRING NOT NULL DEFAULT 'local',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS beliefs (
    belief_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id   UUID NOT NULL REFERENCES agents (agent_id),
    seq        INT8 NOT NULL,
    content    STRING NOT NULL,
    embedding  VECTOR(1024),
    status     belief_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sig        BYTES NOT NULL,
    prev_hash  BYTES NOT NULL,
    hash       BYTES NOT NULL,
    source_id  UUID REFERENCES sources (source_id),
    region     STRING NOT NULL DEFAULT 'local',
    UNIQUE (agent_id, seq),
    INDEX beliefs_source_idx (source_id),
    INDEX beliefs_status_idx (status)
);

CREATE TABLE IF NOT EXISTS derivations (
    child_id   UUID NOT NULL REFERENCES beliefs (belief_id),
    parent_id  UUID NOT NULL REFERENCES beliefs (belief_id),
    kind       derivation_kind NOT NULL,
    score      FLOAT8,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (child_id, parent_id),
    INDEX derivations_parent_idx (parent_id)
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id     UUID NOT NULL REFERENCES sources (source_id),
    opened_by     STRING NOT NULL,
    affidavit_uri STRING,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quarantine_actions (
    action_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id  UUID NOT NULL REFERENCES incidents (incident_id),
    belief_count INT8 NOT NULL,
    actor        STRING NOT NULL,
    sig          BYTES NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_events (
    event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind        STRING NOT NULL,
    incident_id UUID,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

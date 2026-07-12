-- W3 (docs/plans/2026-07-10-week3.md sections 1 and 4).
--
-- fanout_deliveries: durable per-consumer delivery ledger for the outbox
-- poll. memory_events stays append-only (it is W4 audit evidence); the poll
-- is an anti-join against this table, which cannot skip an event the way a
-- timestamp cursor can. PRIMARY KEY (event_id, consumer) makes a duplicate
-- delivery a conflict, and the worker writes the row in the same serializable
-- transaction as the evictions it records: exactly-once effect per consumer.
CREATE TABLE IF NOT EXISTS fanout_deliveries (
    event_id        UUID NOT NULL REFERENCES memory_events (event_id),
    consumer        STRING NOT NULL,
    delivered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    evicted_rows    INT8 NOT NULL DEFAULT 0,
    aborted_actions INT8 NOT NULL DEFAULT 0,
    PRIMARY KEY (event_id, consumer)
);

-- agent_actions: pending side effects an agent has queued on the basis of
-- specific beliefs. derived_from is UUID[] (CockroachDB has no FK-over-array);
-- the eviction worker aborts pending actions via derived_from && $evicted,
-- which is time-independent: an action enqueued after the recant commit but
-- before the worker pass still aborts. The status index keeps the pending
-- scan small; an inverted index on derived_from is a W6 scale item.
CREATE TABLE IF NOT EXISTS agent_actions (
    action_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id      UUID NOT NULL REFERENCES agents (agent_id),
    kind          STRING NOT NULL,
    payload       JSONB NOT NULL,
    derived_from  UUID[] NOT NULL,
    status        STRING NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'executed', 'aborted')),
    status_reason STRING,
    incident_id   UUID REFERENCES incidents (incident_id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ,
    INDEX agent_actions_status_idx (status)
);

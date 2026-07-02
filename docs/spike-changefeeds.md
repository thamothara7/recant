# Spike: Changefeeds on CockroachDB Cloud Basic (Week 1, Task 10)

Date: 2026-07-02. Research done against public documentation only; the real
cluster does not exist yet (user-gated item U1), so nothing here has been
verified against a live Basic cluster.

## Question

Spec section 4, W1 spike: can the eviction fanout pipeline (proof moment 4)
be driven by a CockroachDB changefeed on the Cloud Basic (free) tier, and
specifically by a webhook sink? What limits apply on Basic (sinks allowed,
message size, billing), and are zone configs such as `gc.ttlseconds`
configurable there?

## Findings

1. Changefeeds are enabled by default on Basic. The changefeed configuration
   docs state: "If you are working on a CockroachDB Basic or Standard
   cluster, the `kv.rangefeed.enabled` cluster setting is enabled by
   default." Self-hosted and Advanced clusters must enable it manually.
   Source: https://www.cockroachlabs.com/docs/stable/create-and-configure-changefeeds

2. The Cloud billing docs say changefeeds work on every Cloud plan: "All
   CockroachDB Cloud clusters can use changefeeds." On Basic, CDC cost is
   usage-based via Request Units; on Standard and Advanced it is billed
   monthly by watched table size (GiB-month tiers).
   Source: https://www.cockroachlabs.com/docs/cockroachcloud/costs

3. The CDC overview lists product availability as "All products" for both
   sinkless changefeeds and sink-connected changefeeds. No plan-specific
   sink restrictions are documented.
   Source: https://www.cockroachlabs.com/docs/stable/change-data-capture-overview

4. Supported sinks include webhook (plus Kafka, cloud storage, Google
   Pub/Sub, Confluent Cloud, Azure Event Hubs, Amazon MSK, Pulsar). Webhook
   sink constraints: HTTPS only, JSON output only, batching controlled via
   `webhook_sink_config` (warning: setting `Messages` or `Bytes` without
   `Frequency` makes frequency infinite and can delay delivery
   indefinitely), default retry of 3 attempts with 500 ms backoff doubling
   to a 30 s cap. No hard message size limit is documented for the webhook
   sink.
   Source: https://www.cockroachlabs.com/docs/stable/changefeed-sinks

5. Conflict worth flagging: the marketing pricing comparison table lists an
   "Enterprise changefeeds" row checked only for Standard and Advanced, not
   Basic. This contradicts the docs in findings 2 and 3. It may reflect the
   GiB-month CDC billing feature rather than changefeed availability, but it
   cannot be resolved from documentation alone.
   Source: https://www.cockroachlabs.com/pricing/

6. Free allowance on Basic: 50 million RUs and 10 GiB storage free per
   month (a 15 USD monthly credit). A changefeed to an external sink is
   background activity that consumes RUs, so a long-running webhook
   changefeed draws down the free allowance continuously.
   Sources: https://www.cockroachlabs.com/pricing/ and
   https://www.cockroachlabs.com/docs/cockroachcloud/plan-your-cluster-basic

7. Zone configs on Basic: current docs do not state whether
   `ALTER ... CONFIGURE ZONE` (including `gc.ttlseconds`) works on Basic.
   The replication controls page documents `gc.ttlseconds` with no
   plan-level caveats, but historically CockroachDB Serverless (Basic's
   predecessor) had a fixed `gc.ttlseconds` of 4500 s that could not be
   altered (third-party report, 2023). Treat zone configs as unavailable on
   Basic until proven otherwise on the live cluster.
   Sources: https://www.cockroachlabs.com/docs/stable/configure-replication-zones
   and https://authzed.com/blog/crdb_v23

## Decision

- Primary: `CREATE CHANGEFEED FOR TABLE memory_events INTO '<webhook
  sink>'` consumed by the fanout Lambda behind an HTTPS endpoint. The docs
  (findings 1-4) support this on Basic, it is push-based, and it exercises
  the CockroachDB feature the demo wants to show.
- Fallback: poll the `memory_events` outbox table (already created in
  migration 0001) with an ordered `SELECT ... WHERE created_at > $1` loop.
  Both paths sit behind the same `EvictionBus` interface so Week 3 code is
  sink-agnostic; if finding 5 turns out to mean webhook changefeeds are
  blocked on Basic, only the bus implementation changes.
- Zone configs stay out of the migration chain (decision 7 in the Week 1
  plan header): numbered migrations must apply cleanly on Basic, so
  `gc.ttlseconds` for the AOST forensics window is applied only on the
  self-hosted chaos cluster via `ops/chaos/configure-gc.sh`.

## Open items (need the live cluster from U1)

- Confirm `CREATE CHANGEFEED ... INTO webhook-https://...` succeeds on a
  real Basic cluster, resolving the docs-vs-pricing-table conflict
  (finding 5).
- Confirm whether `ALTER TABLE beliefs CONFIGURE ZONE USING gc.ttlseconds`
  is accepted on Basic, and what the effective AOST window is if not.
- Measure RU burn of an idle and an active webhook changefeed against the
  50M RU monthly allowance.
- Verify webhook batch and payload size behavior empirically; no documented
  message size limit was found.
- Confirm `CREATE VECTOR INDEX` works on Cloud Basic (see note below).

## Related availability notes (Tasks 4 and 9)

- Vector index: migration `db/migrations/0002_vector_index.sql` issues
  `CREATE VECTOR INDEX beliefs_embedding_idx ON beliefs (embedding)`.
  Support on the local docker image (`cockroachdb/cockroach:latest-v26.2`)
  is unverified until Task 12 runs migrations against the chaos cluster. If
  a target cluster rejects it, the fallback is exact nearest-neighbor
  search (`ORDER BY embedding <-> $1 LIMIT k` without an index), which is
  acceptable at demo scale; do not silently skip the migration.
- Zone configs: deliberately excluded from numbered migrations (decision 7
  in the Week 1 plan header). Self-hosted clusters get
  `gc.ttlseconds = 86400` on `beliefs` from `ops/chaos/configure-gc.sh`;
  Cloud Basic handling is tracked in the open items above.

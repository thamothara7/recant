# Recant

"Recant: when an agent's memory goes bad, take it back. Everywhere. Provably."

An agent fleet shares memory. One poisoned source, a stale vendor page, a forum
post, gets ingested by one agent, then paraphrased into a second agent's
beliefs with no explicit link back to the source. By the time anyone notices,
the bad fact has spread through the fleet, and an ops agent is about to act on
it.

Recant is chain of custody for machine memory. Every belief an agent stores
carries a signed, provenance-linked custody record: which agent wrote it, what
source it came from, and a hash chain back to every prior belief that agent
has ever written. When a source turns out to be poisoned, one call,
`recant(source_id)`, quarantines every belief derived from it across the whole
fleet in a single serializable transaction, including beliefs that only match
semantically and carry no explicit provenance edge. A changefeed evicts the
belief from any agent about to act on it, and a forensic query can prove
exactly what any agent believed at any point in the past.

Memory poisoning is the successor to prompt injection: once agents remember
and share what they learn, one bad source becomes a fleet-wide liability.
Recant is not a RAG app, not a chatbot, and not a memory layer. It is the
provenance and retraction substrate underneath memory layers, the same role
Sigstore and SLSA play for the software supply chain.

## Status: Week 1 of 6

What works today:

- Full CockroachDB schema (`sources`, `agents`, `beliefs`, `derivations`,
  `incidents`, `quarantine_actions`, `memory_events`) applied by numbered raw
  SQL migrations, with a vector index on belief embeddings and a row-level TTL
  for beliefs sourced from untrusted-tier sources. Confirmed Jul 2 against the
  local `cockroachdb/cockroach:latest-v26.2` arm64 image: `CREATE VECTOR
  INDEX` applies cleanly (migrations 0001-0003).
- attest-gateway: the only write path into memory. Every belief write happens
  inside one serializable transaction that reads the agent's chain head
  `FOR UPDATE`, computes a hash-chained payload, signs it with a deterministic
  Ed25519 dev key, and advances the head. Writes retry on SQLSTATE 40001 with
  jitter. Belief writes accept an optional client-supplied embedding; there is
  no fake embedder yet (see AWS services table below).
- Deterministic seed fixtures (3 agents, 4 sources, 7 beliefs, including one
  explicit derivation edge) created entirely through the gateway API.
- A local 3-node CockroachDB chaos cluster (`ops/chaos/`), bound to loopback
  only, for the node-kill proof moment, and a changefeed-tier spike report
  (`docs/spike-changefeeds.md`).
- Unit tests for the hash chain, dev signer, migration runner, and
  transaction retry policy, plus an integration suite for the gateway that is
  skipped unless `DATABASE_URL` is set. The full suite is 33 tests (17 unit,
  16 integration) and green against the live local cluster, including
  regression tests for chain-signature forgery and tail truncation.

Not yet built: the taint engine, quarantine service, changefeed fanout,
forensics API, demo fleet agents, and console. See the architecture summary
below for what each of those is and when it lands.

## Architecture

Recant is a set of independently runnable components, one per directory:

| Component | Directory | Purpose | Status |
|---|---|---|---|
| attest-gateway | `services/attest_gateway/` | The only write path into memory: attested, hash-chained, signed belief writes | Built |
| taint-engine | `services/taint_engine/` (planned) | Explicit closure via a recursive CTE over `derivations`; implicit closure via vector kNN within a contamination window | Not yet built, targeted Week 2 |
| quarantine-service | `services/quarantine/` (planned) | Executes `recant(source_id)`: one serializable transaction that flips the full closure to quarantined and writes the incident | Not yet built, targeted Week 2 |
| fanout | `fanout/` (planned, Lambda + EventBridge) | Changefeed webhook to eviction notices; demo agents evict caches and abort in-flight actions | Not yet built, targeted Week 3 |
| forensics-api | `services/forensics/` (planned) | AS OF SYSTEM TIME queries, custody-chain reads, Bedrock-generated incident affidavits | Not yet built, targeted Week 4 |
| fleet | `fleet/` (planned) | Three demo agents (researcher, support, ops) on LangChain with CockroachDB-backed memory | Not yet built, targeted Week 3 |
| console | `console/` (planned) | Frontend, built under the `recant-frontend` skill | Not yet built, targeted Week 5 |

## Quickstart

```bash
git clone https://github.com/thamothara7/recant.git
cd recant
uv sync

ops/chaos/init.sh
export DATABASE_URL=postgresql://root@localhost:26257/recant?sslmode=disable

uv run python -m db.migrate
```

Run the tests next, before seeding:

```bash
uv run pytest
```

Tests under `tests/integration/` skip automatically unless `DATABASE_URL` is
set; unit tests under `tests/unit/` always run. The integration suite deletes
every row from every table before each test, so running it against a seeded
database wipes the seed data; reseed afterward (below) if you want data to
inspect.

Now start the gateway:

```bash
uv run uvicorn services.attest_gateway.app:app --port 8000
```

In another terminal, with `DATABASE_URL` exported the same way:

```bash
uv run python ops/seed/seed.py
```

Expected output: `seeded 3 agents, 4 sources, 7 beliefs`.

Then verify a chain, for example the `researcher` agent seeded above:

```bash
AGENT_ID=$(docker compose -f ops/chaos/docker-compose.yml exec -T roach1 \
    ./cockroach sql --insecure --host=roach1:26257 -d recant --format=csv \
    -e "SELECT agent_id FROM agents WHERE name = 'researcher'" | tail -n1)
curl http://localhost:8000/agents/$AGENT_ID/chain/verify
```

## CockroachDB tools

| Tool | What the agent does with it | Status |
|---|---|---|
| CockroachDB Cloud Managed MCP Server | During development, connects for schema inspection and query-plan analysis, read-only. In the product, the Investigator agent answers forensic questions such as "is this belief clean, show its custody chain" through read-only MCP tool calls, fully audit-logged. | Blocked on U1 (cluster signup); connection steps recorded in `docs/mcp-setup.md`. |
| Distributed Vector Indexing | `VECTOR(1024)` column on `beliefs` (`db/migrations/0001_schema.sql`) with a vector index (`db/migrations/0002_vector_index.sql`) for implicit taint tracing, finding paraphrased contamination with no explicit provenance edge, and similar-incident retrieval. | Confirmed Jul 2: `CREATE VECTOR INDEX` applies cleanly against the local `cockroachdb/cockroach:latest-v26.2` arm64 image. Support on CockroachDB Cloud Basic is unverified until U1 provides a live cluster. |
| ccloud CLI | Drives cluster provisioning, service-account creation, and audit-log retrieval with `--json` output from scripts under `ops/`; the demo's ops agent runs a scripted health check on camera. | Blocked on U2 (CLI install and service account); targeted Week 3. |
| CockroachDB Agent Skills repo | Schema design review and statement or performance profiling invoked against this repo, with before and after recorded in `docs/agent-skills-log.md`. | Pending, blocked on U1 (needs a live cluster); entries queued in `docs/agent-skills-log.md`. |

## AWS services

| Service | What the agent does with it | Status |
|---|---|---|
| Amazon Bedrock | Titan Text Embeddings V2 (1024 dimensions) for belief embeddings; Claude for incident affidavits and apply or distinguish reasoning. | Not yet integrated; Week 1 stores an optional client-supplied embedding only, no fake embedder exists yet. A deterministic fake embedder arrives in Week 2 alongside the taint-engine tests. Blocked on U3 (AWS credentials). |
| AWS Lambda | Consumes the changefeed webhook and fans out eviction notices to demo agents. | Not yet built; targeted Week 3, blocked on U3. |
| Amazon S3 (Object Lock) | Immutable evidence archive for belief history beyond the CockroachDB GC window. | Not yet built; targeted Week 4, blocked on U3. |
| Amazon EventBridge | Event bus between the changefeed Lambda and agent runtimes for cache eviction. | Not yet built; targeted Week 3, blocked on U3. |

## Failure modes

| Failure mode | Handling |
|---|---|
| Changefeed unavailable on the CockroachDB tier | Fallback designed, not yet built: poll the `memory_events` outbox table behind the same `EvictionBus` interface, so calling code would not change. Targeted Week 3 alongside fanout. See `docs/spike-changefeeds.md`. |
| KMS unavailable in development | A deterministic Ed25519 dev signer derives keys from the agent name and is clearly labeled as a dev signer; production replaces it with an AWS KMS signer behind the same `Signer` interface (Week 4). |
| Node loss | The local chaos cluster runs 3 CockroachDB nodes; the cluster and in-flight forensics queries survive the loss of 1 node. |
| Serialization conflicts | Writes that hit SQLSTATE 40001 are retried with jitter (`services/common/db.py`) instead of surfaced to the caller. |

## Cost estimate

- CockroachDB Cloud Basic: free tier (50 million request units and 10 GiB
  storage per month) covers the primary cluster.
- ECS Fargate: one 0.25 vCPU task running the attest-gateway continuously
  costs roughly 9 to 12 USD per month.
- AWS Lambda, EventBridge, and S3: expected to stay within the AWS Free Tier
  at demo scale, given the low request volume and small evidence archive.
- Amazon Bedrock: Titan embeddings and Claude calls are billed per token; at
  demo scale (dozens of beliefs, a handful of affidavits) this comes to
  pennies.

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

Live console (deterministic demo, no backend needed): https://recant.vercel.app

## Status

The full contamination-to-recant-to-proof path works end to end. 150 tests
green against the live local 3-node cluster.

- **Attested writes (attest-gateway).** The only write path into memory. Every
  belief write runs in one serializable transaction that reads the agent's
  chain head `FOR UPDATE`, hash-chains and Ed25519-signs the payload, and
  advances the head; writes retry on SQLSTATE 40001 with jitter. A direct
  `UPDATE` that bypasses the gateway is caught by chain and signature
  verification (regression-tested).
- **Taint engine + recant.** `recant(source_id)` runs one serializable
  transaction that computes the full contamination closure, explicit edges via
  a recursive CTE over `derivations` plus vector kNN for paraphrased copies
  that carry no provenance edge, flips it all to quarantined, opens the
  incident, and writes an attested, self-verifying quarantine action.
- **Fleet + eviction.** Three agents (researcher, support, ops) on
  langchain-cockroachdb working memory. An outbox worker fans the recant out to
  running agents: it deletes evicted beliefs from working memory and aborts
  pending actions resting on them, exactly-once per consumer via a durable
  delivery ledger.
- **Forensics API.** AS OF SYSTEM TIME belief history (time travel), custody
  chain and single-belief provenance with live chain + signature verification,
  incident summaries that re-verify each quarantine action from stored rows,
  Bedrock Claude affidavits (with a deterministic template fallback), and an S3
  evidence-bundle archive. Tamper is proven detected, not just assumed.
- **Console.** The judge-facing UI (`console/`, Material 3, deployed to Vercel).
  Story mode is a scripted walkthrough; Explore drives the live backend when
  configured (real board, real recant, real time-travel), and falls back to
  deterministic fixtures otherwise.
- **AWS, live.** Bedrock Titan Text Embeddings V2 (verified 1024-dim, threshold
  calibrated) and Claude affidavits; S3 evidence archive; the changefeed to
  Lambda to EventBridge fanout is deployed and the consumer leg is verified
  end to end on the cloud cluster.
- **CockroachDB Cloud.** Serverless cluster on AWS us-east-1 (v26.2.1), all six
  migrations applied, connected via the Managed MCP Server (read-only).

Remaining (W6): seed at scale, the demo video, and this README's final polish.
One AWS item waits on account age: the receiver's public function URL (the
changefeed webhook target) is blocked by a new-account public-endpoint
restriction, so the local outbox poll stays the eviction transport until it
clears.

## Architecture

Recant is a set of independently runnable components, one per directory:

| Component | Directory | Purpose | Status |
|---|---|---|---|
| attest-gateway | `services/attest_gateway/` | The only write path into memory: attested, hash-chained, signed belief writes | Built |
| taint-engine | `services/taint_engine/` | Explicit closure via a recursive CTE over `derivations`; implicit closure via vector kNN within a contamination window | Built |
| quarantine-service | `services/quarantine/` | Executes `recant(source_id)`: one serializable transaction that flips the full closure to quarantined and writes the attested incident | Built |
| fanout | `fanout/` (Lambda + EventBridge) | Changefeed webhook to eviction notices; agents evict working memory and abort in-flight actions. Local outbox worker plus deployed cloud receiver and consumer Lambdas | Built (cloud webhook ingress pending account age) |
| forensics-api | `services/forensics/` | AOST time travel, custody-chain and provenance reads, Bedrock Claude affidavits, S3 evidence archive | Built |
| fleet | `fleet/` | Three demo agents (researcher, support, ops) on langchain-cockroachdb working memory | Built |
| console | `console/` | Judge-facing UI built under the `recant-frontend` skill; deployed to Vercel | Built |

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

Now start the three services (each in its own terminal, all with `DATABASE_URL`
exported the same way):

```bash
uv run uvicorn services.attest_gateway.app:app --port 8000  # writes
uv run uvicorn services.quarantine.app:app     --port 8001  # recant
uv run uvicorn services.forensics.app:app      --port 8002  # reads
```

Seed the contamination story through the gateway:

```bash
uv run python ops/seed/seed.py
```

Expected output: `seeded 3 agents, 4 sources, 9 beliefs`.

Then recant the poisoned source and watch the closure flip, including the
paraphrased copies that carry no explicit provenance edge:

```bash
SRC=$(curl -s localhost:8002/board | python3 -c \
  "import sys,json;print(next(s['source_id'] for s in json.load(sys.stdin)['sources'] if s['trust_tier']=='untrusted'))")
curl -s -X POST localhost:8001/recant -H 'content-type: application/json' \
  -d "{\"source_id\":\"$SRC\",\"actor\":\"operator\"}" | python3 -m json.tool
```

### Run the console against the live backend

By default the console (`console/`) runs on deterministic fixtures and needs no
backend. To drive it from the live services, start the three above (with
`RECANT_CORS_ORIGINS=http://localhost:5173` set) and run:

```bash
cd console && npm install
VITE_FORENSICS_URL=http://localhost:8002 \
VITE_QUARANTINE_URL=http://localhost:8001 \
  npm run dev
```

Explore mode now reads the real board, the recant runs the real transaction,
and the rewind is a real AOST query. Without the `VITE_*` vars it stays on
fixtures (this is what the deployed demo URL serves).

### Optional: Bedrock and the cloud fanout

Set `RECANT_EMBEDDER=titan` and `RECANT_AFFIDAVIT=bedrock` (with AWS credentials
in the environment) to use live Titan embeddings and Claude affidavits; both
fall back cleanly without credentials. `RECANT_EVIDENCE_BUCKET` enables the S3
archive endpoint. The cloud fanout Lambdas are packaged and deployed by
`fanout/iac/package.sh` and `fanout/iac/deploy.sh`.

## CockroachDB tools

| Tool | What the agent does with it | Status |
|---|---|---|
| Distributed Vector Indexing | `VECTOR(1024)` column on `beliefs` with a cosine vector index (`db/migrations/0002`, rebuilt with `vector_cosine_ops` in `0004`) for implicit taint tracing: finding paraphrased contamination that carries no explicit provenance edge. An EXPLAIN assertion in the suite pins the `vector search` plan node. | Live. Applies on the local v26.2 image and on CockroachDB Cloud serverless v26.2.1. The recant materializes the vector-inferred edges. |
| Serializable transactions | `recant(source_id)` computes and flips the entire contamination closure in one `SERIALIZABLE` transaction; a parked-transaction test proves the flip is all-or-nothing and invisible until commit. | Live. |
| AS OF SYSTEM TIME | The forensics API answers "what did this agent believe at time T" as a time-travel read; the console rewind is backed by it. | Live. |
| Changefeeds | `CREATE CHANGEFEED FOR TABLE memory_events INTO 'webhook-https://...'` drives the cloud eviction fanout. Accepted on the serverless free tier; the local transport is an outbox poll behind the same interface. | Deployed; changefeed creation waits on the receiver's public URL (account age). |
| CockroachDB Cloud Managed MCP Server | Connected read-only for schema inspection and query-plan analysis during development; the same read-only surface backs the product's forensic questions. | Connected (per-session auth). |
| ccloud CLI | Cluster provisioning and inspection with `--json` output. | Installed and authenticated. |

## AWS services

| Service | What the agent does with it | Status |
|---|---|---|
| Amazon Bedrock | Titan Text Embeddings V2 (1024 dimensions) for belief and working-memory embeddings; Claude (via a cross-region inference profile) writes incident affidavits from the stored records at temperature 0. | Live. Titan verified end to end (1024-dim, L2-normalized, threshold calibrated from a live probe); Claude affidavits generate live with a deterministic template fallback. Selected by `RECANT_EMBEDDER=titan` / `RECANT_AFFIDAVIT=bedrock`. |
| AWS Lambda | Two functions: the receiver turns the changefeed webhook into EventBridge events; the consumer applies the eviction on the cloud cluster with the same handler the local worker uses. | Deployed. Consumer verified end to end (applies in 27ms, duplicates no-op through the delivery ledger). |
| Amazon EventBridge | Event bus and rule between the receiver and consumer Lambdas. | Deployed; the receiver-to-bus-to-consumer chain ran hands-free. |
| Amazon S3 | Versioned, private evidence archive: `POST /incidents/{id}/archive` writes the incident summary, affidavit, and per-agent custody chains under one prefix. | Live. Bucket versioned with all public access blocked; verified end to end. |

## Failure modes

| Failure mode | Handling |
|---|---|
| Changefeed unavailable, or its webhook target unreachable | The `memory_events` outbox is polled by a local worker behind the same interface (an anti-join against a durable delivery ledger, immune to timestamp-cursor skip), so eviction is delayed, never lost. The cloud webhook changefeed replaces only the poll loop. This is the active transport today while the receiver's public URL waits on account age. |
| Bedrock unavailable or credentials absent | Titan selection is opt-in (`RECANT_EMBEDDER`); the deterministic HashEmbedder is the default. The Claude affidavit generator falls back to the deterministic text template on any error, and the fallback is visible in the response and the log. |
| KMS unavailable in development | A deterministic Ed25519 dev signer derives keys from the agent name and is clearly labeled as a dev signer; production replaces it with an AWS KMS signer behind the same `Signer` interface. |
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

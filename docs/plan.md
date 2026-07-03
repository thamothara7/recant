# Recant Living Plan

Status values (only these): `pending`, `in progress`, `done`, `blocked`, `cut`.

## Current milestone

**W1** (target: Jul 6) - cluster + MCP + ccloud service account + schema + attested writes + spike report on changefeeds/tier.

## Milestone checklist (spec section 12)

| Week | Target date | Scope | Status |
|------|-------------|-------|--------|
| W1 | Jul 6 | Cluster + MCP + ccloud service account + schema + attested writes + spike report on changefeeds/tier | in progress (code done Jul 2; cloud items blocked on U1/U2) |
| W2 | - | Taint engine (CTE + vector) + quarantine txn + tests | pending |
| W3 | - | Fleet agents on LangChain-CockroachDB + fanout Lambda/EventBridge + eviction | pending |
| W4 | - | Forensics API (AOST) + S3 archive + Bedrock affidavits | pending |
| W5 | - | Console per `recant-frontend` skill + chaos cluster + judge overlay | started early (Jul 3): working shell, Provenance Board, recant flow, Judge Overlay against fixtures |
| W6 | Aug 10-16 | Seed at scale, record video, deploy demo URL, README polish, submit Aug 16 (never on deadline day) | pending |

## Decision log

| # | Decision | Reason |
|---|----------|--------|
| 1 | Services language: Python 3.12 + FastAPI | Spec section 9 offers Python or Go; Python chosen for LangChain compatibility in Week 3. |
| 2 | API deploy target: ECS Fargate, not Lambda | The console needs a native WebSocket ticker and the changefeed webhook needs a long-lived endpoint; one FastAPI container serves both. Fanout stays Lambda + EventBridge as the spec mandates. Estimated cost documented in README. |
| 3 | Embeddings: Bedrock Titan Text Embeddings V2, 1024 dimensions | Column is `VECTOR(1024)`. Week 1 uses an optional client-supplied embedding; a deterministic fake embedder serves tests until Bedrock credentials exist. |
| 4 | Signing: `sig` is Ed25519 over the 32-byte chain hash | Dev keys are derived deterministically from agent name (reproducible demo, spec section 10). KMS signer replaces the dev signer in Week 4 behind the same interface. |
| 5 | Chain ordering: explicit `seq` column per agent | Not `created_at` ordering, which can tie. The chain head (`head_hash`, `head_seq`) lives on the `agents` row and is read with FOR UPDATE, which serializes appends per agent. |
| 6 | Migrations: numbered raw SQL files plus `db/migrate.py` runner with a `schema_migrations` table | No Alembic (spec section 9 allows raw SQL; there is no ORM model to autogenerate from). |
| 7 | Zone configs (`gc.ttlseconds`) are NOT in numbered migrations | They may be restricted on CockroachDB Cloud Basic. Self-hosted chaos cluster applies them via `ops/chaos/configure-gc.sh`; Cloud handling goes in the spike report. |

## Cut list

_Empty. Anything cut per section 7 priority order gets logged here with the reason and the milestone it was cut from._

| Item | Cut from milestone | Reason |
|------|---------------------|--------|

## User setup queue

Items that cannot be completed by the agent; the human must act.

| ID | Item | Status |
|----|------|--------|
| U0 | Restart Claude Code so the newly installed CockroachDB Agent Skills are discovered (install itself is done; see `docs/skills-setup.md`) | pending (agent-side install done Jul 3) |
| U1 | CockroachDB Cloud signup (https://cockroachlabs.cloud/signup) and cluster creation | pending |
| U2 | Install and authenticate ccloud CLI; create service account | pending |
| U3 | AWS account credentials (Bedrock, Lambda, S3, EventBridge access) and `aws` CLI install | pending |
| U4 | Docker Desktop running locally (daemon was unreachable at plan time) | done (started Jul 2; integration pass green) |
| U5 | Connect the CockroachDB Cloud Managed MCP Server to this Claude Code session after U1 | pending |
| U6 | Decide GitHub publication: repo github.com/thamothara7/recant is private and 6+ commits are unpushed; judges need a public repo with pushed HEAD (submission requirement, spec section 2) | pending |

## Risks

| Risk | Impact | Status | Notes |
|------|--------|--------|-------|
| Docker daemon unreachable locally (U4) | Blocks the 3-node chaos cluster (Task 9) and integration verification (Task 12), and therefore the node-kill proof moment | done | Docker Desktop started Jul 2; 3-node cluster runs, node-kill rehearsal passed (forensics query answered with roach3 dead). |
| Changefeed availability on CockroachDB Cloud Basic tier unconfirmed | Fanout eviction (proof moment 4) may need a fallback | in progress | Task 10 spike report written; docs conflict on Basic-tier changefeeds, so treat as unavailable until verified on the live cluster after U1. Fallback stays: memory_events outbox + poller behind the same EvictionBus interface. |
| Vector index support on local `cockroachdb/cockroach:latest-v26.2` image unconfirmed | Local chaos cluster may not support the same vector index DDL as Cloud | done | Confirmed Jul 2: CREATE VECTOR INDEX applied cleanly on the local arm64 latest-v26.2 image (migration 0002). |
| System python was x86_64 | Would not match arm64 target | done | Worked around with uv-managed arm64 CPython 3.12; `.venv` already provisioned. |

## Week 1 integration verification (Jul 2)

- Local 3-node cluster up (cockroachdb/cockroach:latest-v26.2, arm64); init.sh fixed to run SET CLUSTER SETTING outside a multi-statement transaction.
- Migrations 0001-0003 applied, including CREATE VECTOR INDEX; gc.ttlseconds=86400 set on beliefs via configure-gc.sh.
- Full test suite green against the live cluster: 33 passed (17 unit, 16 integration), including regression tests for chain-signature forgery and tail truncation added in the Jul 3 review.
- Seed via gateway API: 3 agents, 4 sources, 7 beliefs; chains verify; 2 explicit derivation edges; 1 untrusted-source belief carries ttl_expire_at.
- Node-kill rehearsal (proof moment 6): chain verification answered with roach3 killed; roach3 restarted after.
- Known cosmetic warnings: starlette TestClient httpx deprecation; psycopg_pool default-open deprecation.

## Console (W5, started early Jul 3)

- `console/`: Vite + React + TS + Tailwind, exact recant-frontend tokens, self-hosted fonts.
- Working: Provenance Board (react-flow + dagre, evidence-tag cards, custody-thread edges), Inspector (custody chain + recant dialog), left rail, AOST scrubber, changefeed ticker, cluster bar with node-kill + live query counter, Judge Overlay + primitive log, Demo Director (keys 1-6), J/V/R toggles.
- Data: deterministic fixtures extending `ops/seed/seed.py` into the full contamination story; no live backend yet (forensics read APIs land W2-W4). The fixture layer mirrors the future API shape for a clean swap.
- Verified: `npm run build` clean; recant sequence exercised end to end at 1280x720.
- Next for the console: wire to the live gateway/forensics APIs as they land; full recant motion sequence (thread pulse + sweep timing polish); Recording Mode countdown; mobile read-only incident summary.

### Deferred to W2

- Structured JSON logging with `incident_id` correlation: incidents do not
  exist until the taint engine and quarantine service land in Week 2, so
  there is nothing to correlate yet.
- Deterministic fake embedder: needed for the Week 2 taint-engine tests
  (implicit closure via vector kNN); Week 1 only accepts an optional
  client-supplied embedding.
- Embedding write-path exercised only via tests until the fleet exists: no
  real agent produces embeddings yet, so the `embedding` column is only
  populated by test fixtures that pass one in explicitly.

# Recant Living Plan

Status values (only these): `pending`, `in progress`, `done`, `blocked`, `cut`.

## Current milestone

**W1** (target: Jul 6) - cluster + MCP + ccloud service account + schema + attested writes + spike report on changefeeds/tier.

## Milestone checklist (spec section 12)

| Week | Target date | Scope | Status |
|------|-------------|-------|--------|
| W1 | Jul 6 | Cluster + MCP + ccloud service account + schema + attested writes + spike report on changefeeds/tier | in progress |
| W2 | - | Taint engine (CTE + vector) + quarantine txn + tests | pending |
| W3 | - | Fleet agents on LangChain-CockroachDB + fanout Lambda/EventBridge + eviction | pending |
| W4 | - | Forensics API (AOST) + S3 archive + Bedrock affidavits | pending |
| W5 | - | Console per `recant-frontend` skill + chaos cluster + judge overlay | pending |
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
| U1 | CockroachDB Cloud signup (https://cockroachlabs.cloud/signup) and cluster creation | pending |
| U2 | Install and authenticate ccloud CLI; create service account | pending |
| U3 | AWS account credentials (Bedrock, Lambda, S3, EventBridge access) and `aws` CLI install | pending |
| U4 | Docker Desktop running locally (daemon was unreachable at plan time) | pending |
| U5 | Connect the CockroachDB Cloud Managed MCP Server to this Claude Code session after U1 | pending |

## Risks

| Risk | Impact | Status | Notes |
|------|--------|--------|-------|
| Docker daemon unreachable locally (U4) | Blocks the 3-node chaos cluster (Task 9) and integration verification (Task 12), and therefore the node-kill proof moment | blocked | Daemon was unreachable at plan time; needs Docker Desktop running before Tasks 9 and 12 can proceed. |
| Changefeed availability on CockroachDB Cloud Basic tier unconfirmed | Fanout eviction (proof moment 4) may need a fallback | pending | To be confirmed in Task 10 spike report; fallback is an outbox table + poller behind the same interface. |
| Vector index support on local `cockroachdb/cockroach:latest-v26.2` image unconfirmed | Local chaos cluster may not support the same vector index DDL as Cloud | pending | To be confirmed in Task 12. |
| System python was x86_64 | Would not match arm64 target | done | Worked around with uv-managed arm64 CPython 3.12; `.venv` already provisioned. |

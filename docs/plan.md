# Recant Living Plan

Status values (only these): `pending`, `in progress`, `done`, `blocked`, `cut`.

## Current milestone

**W6** (target: Aug 10-16) - production hardening, seed at scale, record the demo, and submit.

## Milestone checklist (spec section 12)

| Week | Target date | Scope | Status |
|------|-------------|-------|--------|
| W1 | Jul 6 | Cluster + MCP + ccloud service account + schema + attested writes + spike report on changefeeds/tier | in progress (code done Jul 2). Cloud landed Jul 12: serverless cluster "recant" on AWS us-east-1 (v25.4.10, $0 spend limit), all 6 migrations applied clean, MCP server registered (needs browser auth). Serverless spike findings: kv.rangefeed.enabled already True; CREATE CHANGEFEED accepted (webhook fanout viable on the free tier); vector indexes + row-level TTL + cosine opclass all apply on v25.4. See decision 22. |
| W2 | - | Taint engine (CTE + vector) + quarantine txn + tests | done (Jul 3, review-hardened Jul 4): full suite 68 green against chaos cluster; see W2 section |
| W3 | - | Fleet agents on LangChain-CockroachDB + fanout Lambda/EventBridge + eviction | (a) local done (Jul 10): fleet + outbox worker + eviction + lambda_entry unit-tested, proof moment 4 rehearsed (3 evicted, 1 aborted, apply 31ms); (b) cloud leg DEPLOYED (Jul 16, 7beca41): Titan embeddings live (2486513), consumer Lambda + EventBridge bus + SSM SecureString + least-privilege roles deployed via fanout/iac/; verified live on the cloud cluster: consumer applies in 27ms, duplicates no-op through the fanout_deliveries ledger, and the receiver -> bus -> consumer -> ledger chain ran hands-free. Aug 12 review found the 403 cause: AWS now requires both `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` for new public Function URLs. `deploy.sh` grants both, with direct invocation blocked. REMAINING: rerun the deployment, verify the Basic-authenticated URL, then create the cloud changefeed. Local outbox poll remains the fallback (decision 18). Plan: docs/plans/2026-07-10-week3.md |
| W4 | - | Forensics API (AOST) + S3 archive + Bedrock affidavits | DONE (Jul 16). Forensics API (29e5e23): AOST belief history, custody-chain + provenance verification, incident summary re-verifying each action from stored rows, tamper-detection tests. Bedrock Claude affidavits with template fallback (60f87fd, us.anthropic.claude-haiku-4-5 inference profile, verified live). S3 evidence archive (3549de9, POST /incidents/{id}/archive, versioned private bucket recant-evidence-474550261608, verified live). Full suite 150 green. |
| W5 | - | Console per `recant-frontend` skill + chaos cluster + judge overlay | DONE for the demo (Jul 16). Material 3 (decision 17), logo v2 (R monogram + custody thread), tutorial completion remembered (localStorage), responsive mobile summary <1024px, deployed to Vercel (recant.vercel.app). WIRED to live APIs (9f10855 + 0e9012f): GET /board endpoint; one flag, two modes (fixtures default, live when VITE_FORENSICS_URL/VITE_QUARANTINE_URL set); Story always fixtures, Explore live. Verified end to end: real board, real recant materializes vector-inferred edges and flips 3 across 3 bots, real AOST rewind. Adversarial review found 4 defects (half-live no-op, enum crash guard, fetch timeout, recantedSource clobber), all fixed. |
| W6 | Aug 10-16 | Production hardening, seed at scale, record video, deploy demo URL, README polish, submit Aug 16 | in progress. Demo URL deployed (recant.vercel.app). Aug 12 hardening added tenant RLS, bearer RBAC, KMS signing, provenance non-amplification, Recant Guard, encrypted atomic idempotency, custody checkpoints, authenticated fanout with retry/DLQ, tenant-prefixed vector search, pinned dependencies, CI, and contributor guidance. Release verification: 248 tests passed; all 11 migrations applied to a fresh CockroachDB instance; Ruff, mypy, dependency audits, Lambda package isolation, and the production console build passed. REMAINING: seed at scale, rerun the updated AWS fanout deployment, record the sub-3-minute video (user, on camera), and final submission. |

## Decision log

| # | Decision | Reason |
|---|----------|--------|
| 1 | Services language: Python 3.12 + FastAPI | Spec section 9 offers Python or Go; Python chosen for LangChain compatibility in Week 3. |
| 2 | API deploy target: ECS Fargate, not Lambda | The console needs a native WebSocket ticker and the changefeed webhook needs a long-lived endpoint; one FastAPI container serves both. Fanout stays Lambda + EventBridge as the spec mandates. Estimated cost documented in README. |
| 3 | Embeddings: Bedrock Titan Text Embeddings V2, 1024 dimensions | Column is `VECTOR(1024)`. Week 1 uses an optional client-supplied embedding; a deterministic fake embedder serves tests until Bedrock credentials exist. |
| 4 | Signing: `sig` is over the 32-byte chain hash | Dev keys are deterministic Ed25519 keys for a reproducible demo. Production requires per-agent AWS KMS ECDSA P-256 keys and a separate control-plane KMS key; every signed record stores its algorithm, key ID, and public key for offline verification. |
| 5 | Chain ordering: explicit `seq` column per agent | Not `created_at` ordering, which can tie. The chain head (`head_hash`, `head_seq`) lives on the `agents` row and is read with FOR UPDATE, which serializes appends per agent. |
| 6 | Migrations: numbered raw SQL files plus `db/migrate.py` runner with a `schema_migrations` table | No Alembic (spec section 9 allows raw SQL; there is no ORM model to autogenerate from). |
| 7 | Zone configs (`gc.ttlseconds`) are NOT in numbered migrations | They may be restricted on CockroachDB Cloud Basic. Self-hosted chaos cluster applies them via `ops/chaos/configure-gc.sh`; Cloud handling goes in the spike report. |
| 8 | Vector index uses a tenant prefix and `vector_cosine_ops` (migrations 0004 and 0009) | The default opclass is L2-only, so cosine `<=>` otherwise full-scans. A global top-K can also be crowded by other tenants before application filtering. The index and query now use `(tenant_id, embedding vector_cosine_ops)`, and an EXPLAIN assertion pins the `vector search` plan node. |
| 9 | Taint threshold is a property of the embedder; the seed story uses controlled vectors | HashEmbedder similarity is lexical and cannot separate "same claim reworded" from "same topic, different claim" (live run quarantined the clean 30-day policy). Story beliefs get basis-vector mixtures (paraphrase pinned at the console fixture's 0.91); `check_story()` proves both directions (paraphrase caught, every clean belief clear) before seeding. HashEmbedder (default 0.35) stays for arbitrary dev content; Titan + threshold calibration land in W3. |
| 10 | Contamination window anchors to `sources.created_at` (LEAST with first citation) | An unrecorded paraphrase can predate the first recorded citation; anchoring to citations would let it survive the recant (design review Jul 3). |
| 11 | `suspect` producer: the gateway write path | A new belief citing a source with an open incident, or deriving from a suspect/quarantined parent, is born `suspect`. Closes the post-recant residue gap on the write side; runtime eviction is W3. |
| 12 | Eviction contract: `memory_events.payload.evictions = [{agent_id, belief_ids}]` | Built from the flip's RETURNING pairs (newly flipped only), so repeat recants do not re-evict. The W3 fanout keys on this shape. |
| 13 | Row-level TTL stays FK-blocked, window env-configurable | TTL deletes are ordinary DELETEs and derivations FKs (NO ACTION) block them: the job errors, rows persist, provenance is never severed; documented in failure modes. `RECANT_UNTRUSTED_TTL_DAYS` (deployed demo sets 90 so nothing expires mid-judging). |
| 14 | Attested action is self-verifying from stored rows; action keys are domain-separated | Post-review 2026-07-04: the signed payload binds `newly_flipped_ids`, which previously survived only in the unsigned outbox event, so a DB-only forensics verifier could not recompute it; migration 0005 persists `quarantine_actions.newly_flipped_ids`. And action signing moved to a disjoint keyspace (`recant-dev-action:{actor}` via `dev_action_signer_for`) so an unauthenticated `actor` string can never forge a signature that verifies under an agent's belief-chain pubkey. Pinning `actor` to a KMS key ARN registry is W4. |
| 15 | One clock domain for the contamination window | Post-review 2026-07-04: `beliefs.created_at` was the gateway host wall clock while `sources.created_at` is the DB `now()`; the window compares the two, so host/DB skew shifted the boundary. The gateway now stamps `created_at` from the DB clock (`SELECT now()` inside the txn), matching the source timestamp. |
| 16 | Closure incompleteness is two distinct signals | Post-review 2026-07-04: `capped` conflated the 10-round runaway guard with adaptive-K truncation at `max_k`, and the operator log misattributed the cause. Split into `rounds_capped` / `knn_truncated`, logged distinctly, exposed in `ClosureOut`. Inferred-edge parent is now the highest-similarity probe per hit (was first-in-scan-order). Retracted kNN hits still stop implicit traversal (asymmetric with the explicit path); not demo-reachable in W2 (no retract API); revisit when a retract path ships. |
| 17 | Console redesigned on Material 3; UV theme retired | User feedback 2026-07-10: the dark violet "UV forensic" look read as AI-generated. Tokens are now M3 color roles HCT-derived from seed #0B57D0 via `@material/material-color-utilities` (`console/scripts/gen-m3-tokens.mjs`), light default with a dark scheme behind `data-theme="dark"`; Roboto / Roboto Mono / Material Symbols self-hosted; Gmail-style shell with the board as the hero surface card; statuses render as tonal chips (icon + label, never color alone). The `recant-frontend` skill now mandates M3 and bans the old look. Judge Overlay, Demo Director, Recording Mode, and all board behavior unchanged. |
| 18 | W3 local eviction transport: poll the append-only outbox, anti-join delivery ledger | The unlicensed 3-node cluster throttles to 5 concurrent transactions after a 7-day grace (hit live 2026-07-10; volume reset is the scripted mitigation), the webhook sink is HTTPS-only locally, and a sinkless consumer would not de-risk the Lambda's webhook envelope anyway. `memory_events` stays append-only (W4 audit evidence); delivery state lives in `fanout_deliveries` keyed (event_id, consumer), and the poll is an anti-join, immune to the timestamp-cursor outbox skip hazard. The Cloud webhook changefeed replaces only the poll loop under U1+U3. |
| 19 | One fanout handler module, two entrypoints | `fanout/handler.py` (parse_event + apply_evictions) is transport-agnostic with no AWS imports at module scope; the local worker and `fanout/lambda_entry.py` (written and unit-tested now, deployed under U3) are thin shims. apply_evictions runs inside the caller's transaction, so evictions, action aborts, the receipt event, and the delivery row commit atomically: exactly-once effect per consumer, crash-safe by rollback. |
| 20 | Working memory on langchain-cockroachdb 0.2.1, with two pinned workarounds | Table is package-bootstrapped (not in the migration chain; shape pinned by test): id UUID = belief_id (the custody link; retried mirrors are upserts), namespace column = agent_id (one table, one-statement eviction, per-agent retrieval). Workarounds proven by spike: NullPool (the package's sync wrappers run each call in a fresh event loop and pooled asyncpg connections die cross-loop) and OUR index DDL (`(agent_id, embedding vector_cosine_ops)`): CSPANNIndex omits the opclass while the package queries `<=>`, which full-scans, the decision-8 lesson verbatim. EXPLAIN pins the `vector search` node in the shape test. |
| 21 | Eviction is a real operation on a materialized copy; transcripts are never edited | `agent_memory` is a runtime copy, not a read-time status filter, so proof moment 4 is an observable DELETE plus a time-independent `derived_from &&` abort of pending actions. Suspect-born beliefs never enter working memory (the fleet honors the gateway's birth status). Chat transcripts are the agent's own record; the visible proof of eviction is the context-assembly diff plus the receipt event. Rehearsed live 2026-07-10: 3 evicted, 1 aborted, apply 31ms. |
| 22 | CockroachDB Cloud target: serverless (Basic) on AWS us-east-1, verify-full over the downloaded cluster CA | Cluster created Jul 12 (id 7177f9f6-5475-4727-ba72-ff1d447458b7, v25.4.10). AWS provider aligns the changefeed->Lambda path and Bedrock (U3) in one region. Free tier ($0 spend limit) carries the full schema: all 6 migrations apply, `kv.rangefeed.enabled` is already True, and `CREATE CHANGEFEED` is accepted, so the W3 cloud webhook leg is viable without a paid tier (the decision-18 outbox poll stays the local fallback). Connection is `sslmode=verify-full` against the CA at `~/.postgresql/root.crt` (macOS libpq has no system PEM bundle, so `sslrootcert=system` fails; the downloaded cert is required). App SQL user `recant_app`; secrets live in the gitignored `.env` as `DATABASE_URL_CLOUD`, never committed. `DATABASE_URL` stays LOCAL so the destructive test suite never truncates cloud tables. |
| 23 | Tenant isolation uses API identity plus CockroachDB RLS | Bearer tokens map to a tenant and least-privilege roles. Every tenant transaction sets a UUID-derived SQL role, and RLS is the database backstop even when an application query omits its tenant predicate. Local development retains a stable default tenant. |
| 24 | Recant Guard is the action boundary | Retrieval receipts bind the exact active context. Immutable signed decisions enforce monotonic source authority, and allowed effects get short-lived, exact-argument, single-use permits consumed at the executor boundary. Recant revokes unused permits in the quarantine transaction. |
| 25 | Semantic taint requires claim evidence across independent sources | Vector similarity can discover unattributed copies. A source-backed belief crosses into another source's closure only with stored equivalence or entailment evidence, or exact normalized content. This prevents a contradictory independent policy from being quarantined on topical similarity alone. |
| 26 | Runtime working memory carries tenant metadata enforced by RLS | The package-owned `agent_memory` schema has no tenant column. Each mirror now stores `tenant_id` in JSON metadata, bootstrap enables a policy over that value, and provisioning grants access only after installing the policy. Tenant roles cannot read or forge another tenant's cache rows. |
| 27 | New quarantine attestations use v2 | V1 remains byte-compatible for historical evidence. V2 additionally binds the tenant and a domain-specific payload type so a valid action signature cannot be transplanted across tenant contexts. |
| 28 | Idempotency responses are AES-256-GCM encrypted | Exact replay can include a one-use Guard permit. Storing that JSON in plaintext would bypass the permit table's hash-only design, so replay rows authenticate tenant, principal, route, key, and request digest as associated data. |
| 29 | Public Lambda Function URLs receive both invocation grants | AWS requires both `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` for new URLs since October 2025. The second grant is restricted with `lambda:InvokedViaFunctionUrl`, and the receiver still enforces the CockroachDB Basic secret. |

## Cut list

_Empty. Anything cut per section 7 priority order gets logged here with the reason and the milestone it was cut from._

| Item | Cut from milestone | Reason |
|------|---------------------|--------|

## User setup queue

Items that cannot be completed by the agent; the human must act.

| ID | Item | Status |
|----|------|--------|
| U0 | Restart Claude Code so the newly installed CockroachDB Agent Skills are discovered (install itself is done; see `docs/skills-setup.md`) | done (verified Jul 12: symlink live, 34 SKILL.md files discoverable at `~/.claude/skills/cockroachdb-skills`) |
| U1 | CockroachDB Cloud signup (https://cockroachlabs.cloud/signup) and cluster creation | done (Jul 12): logged in as Thamothara N / org "Jaya Engineering College" (org-3bcjm); serverless cluster "recant" created on AWS us-east-1, schema migrated. See decision 22. |
| U2 | Install and authenticate ccloud CLI; create service account | ccloud CLI installed and authenticated (Jul 12, `~/bin/ccloud` 0.6.12); SQL user `recant_app` created for app connections. A ccloud API service account (for the audit-log retrieval script, W3) is not yet created; add only if that script needs programmatic ccloud API access. |
| U3 | AWS account credentials (Bedrock, Lambda, S3, EventBridge access) and `aws` CLI install | DONE (Jul 16). CLI: broken Homebrew build (python@3.14 pyexpat ABI crash) replaced with the official AWS pkg installed per-user to ~/aws-cli (self-contained arm64, aws-cli/2.35.24 exe/arm64), symlinked into ~/bin, brew build unlinked. Account 474550261608, IAM user `recant-cli` with AdministratorAccess (tighten to scoped Bedrock/S3/Lambda/EventBridge policy before submission). Bedrock model access is now automatic in us-east-1 (the manual Model access page is retired); verified live: `amazon.titan-embed-text-v2:0` invoke returns a 1024-dim L2-normalized vector (norm 1.0, matches VECTOR(1024) + cosine index), and `anthropic.claude-haiku-4-5-20251001-v1:0` / `anthropic.claude-sonnet-5` are listed for affidavits. Phase 3 wiring (Titan embeddings, S3 archive, Claude affidavits, Lambda/EventBridge fanout) can proceed. |
| U4 | Docker Desktop running locally (daemon was unreachable at plan time) | done (started Jul 2; integration pass green) |
| U5 | Connect the CockroachDB Cloud Managed MCP Server to this Claude Code session after U1 | server registered Jul 12 at local scope (`claude mcp add cockroachdb-cloud`, header `mcp-cluster-id: 7177f9f6-...`); status "Needs authentication". Remaining user step: run `/mcp`, select cockroachdb-cloud, complete the browser login and "Authorize MCP Access". Stays read-only per decision policy. |
| U6 | Publish repo publicly with pushed HEAD (submission requirement, spec section 2) | done (verified Jul 16 via public GitHub API: github.com/thamothara7/recant is public, private=False, HEAD 29e5e23 pushed). `gh` CLI installed but not logged in; `gh auth login` remains optional (only needed for PR/issue automation, not for submission). |

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

## Week 2 verification (Jul 3)

- Design doc `docs/plans/2026-07-03-week2.md`; pre-implementation adversarial
  review (3 lenses) produced 14 findings, all triaged: 2 blocking fixed before
  they could bite (cosine opclass, embedder/threshold mismatch, both also
  caught empirically first), 7 important applied (window anchor, adaptive K,
  suspect producer, residue ownership, TTL policy, deterministic atomicity
  hook, concurrency-guarantee rewording), notes applied (eviction contract,
  CORS expose) or logged (ANN beam size → W6).
- `services/taint_engine/engine.py`: recursive CTE + cosine kNN fixpoint,
  adaptive K, window anchored to source creation, runs inside the caller's txn.
- `services/quarantine/app.py`: POST /recant (serializable flip + incident +
  attested action + eviction outbox event), POST /taint/preview (read-only),
  judge-overlay headers, CORS expose, incident-correlated JSON logs.
- Gateway: beliefs born `suspect` when citing an incident source or deriving
  from a tainted parent; `RECANT_UNTRUSTED_TTL_DAYS` env.
- Full suite 62 green against the chaos cluster, including: deterministic
  all-or-nothing atomicity (txn parked between flip and commit), transitive
  closure through a vector-inferred member, EXPLAIN pins `vector search` on
  `beliefs_embedding_idx`, TTL-expired-but-visible rows still flip, attested
  quarantine action verifies, second recant flips 0 and audits.
- Seed story extended (`support_paraphrase` with no provenance edge +
  `ops_action` derived from it) using controlled embeddings; `check_story()`
  proves paraphrase-caught AND clean-beliefs-clear before writing (it caught a
  shared-remainder-axis bug in its own first draft). Live demo run verified:
  exactly 3 quarantined, 6 active, inferred edge at 0.91, headers
  `SERIALIZABLE TXN | 80ms` / `VECTOR kNN | 11ms`.
- Post-implementation adversarial review (4 lenses) triaged Jul 4: the
  "critical" self-poisoning finding was stale (written against the old
  HashEmbedder seed; the controlled-vector seed + `check_story` negative
  assertion already prevent it). Two important attestation gaps fixed
  (self-verifying action rows via migration 0005; domain-separated action keys;
  decision 14), the mixed clock domain fixed (decision 15), and the closure
  incompleteness signals split with best-parent inferred edges (decision 16).
  Six tests added: action-payload byte-stability + digest (unit),
  domain-separation, round-cap guard, kNN-truncation (integration); the
  attestation test now reconstructs the payload from stored rows and the
  atomicity reader runs `PRIORITY HIGH` with a pre-commit liveness assertion so
  it no longer silently depends on `kv.transaction.write_buffering`. Re-verified
  live: seed → recant flips exactly 3, action verifies from DB rows alone, and
  the action signature does not verify under the actor's agent key.

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

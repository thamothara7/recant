# Recant Living Plan

Status values (only these): `pending`, `in progress`, `done`, `blocked`, `cut`.

## Current milestone

**W1** (target: Jul 6) - cluster + MCP + ccloud service account + schema + attested writes + spike report on changefeeds/tier.

## Milestone checklist (spec section 12)

| Week | Target date | Scope | Status |
|------|-------------|-------|--------|
| W1 | Jul 6 | Cluster + MCP + ccloud service account + schema + attested writes + spike report on changefeeds/tier | in progress (code done Jul 2; cloud items blocked on U1/U2) |
| W2 | - | Taint engine (CTE + vector) + quarantine txn + tests | done (Jul 3, review-hardened Jul 4): full suite 68 green against chaos cluster; see W2 section |
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
| 8 | Vector index rebuilt with `vector_cosine_ops` (migration 0004) | The 0002 default opclass is L2-only: a cosine `<=>` ORDER BY silently full-scans (verified empirically on v26.2.3). An EXPLAIN assertion in the integration suite pins the `vector search` plan node. |
| 9 | Taint threshold is a property of the embedder; the seed story uses controlled vectors | HashEmbedder similarity is lexical and cannot separate "same claim reworded" from "same topic, different claim" (live run quarantined the clean 30-day policy). Story beliefs get basis-vector mixtures (paraphrase pinned at the console fixture's 0.91); `check_story()` proves both directions (paraphrase caught, every clean belief clear) before seeding. HashEmbedder (default 0.35) stays for arbitrary dev content; Titan + threshold calibration land in W3. |
| 10 | Contamination window anchors to `sources.created_at` (LEAST with first citation) | An unrecorded paraphrase can predate the first recorded citation; anchoring to citations would let it survive the recant (design review Jul 3). |
| 11 | `suspect` producer: the gateway write path | A new belief citing a source with an open incident, or deriving from a suspect/quarantined parent, is born `suspect`. Closes the post-recant residue gap on the write side; runtime eviction is W3. |
| 12 | Eviction contract: `memory_events.payload.evictions = [{agent_id, belief_ids}]` | Built from the flip's RETURNING pairs (newly flipped only), so repeat recants do not re-evict. The W3 fanout keys on this shape. |
| 13 | Row-level TTL stays FK-blocked, window env-configurable | TTL deletes are ordinary DELETEs and derivations FKs (NO ACTION) block them: the job errors, rows persist, provenance is never severed — documented in failure modes. `RECANT_UNTRUSTED_TTL_DAYS` (deployed demo sets 90 so nothing expires mid-judging). |
| 14 | Attested action is self-verifying from stored rows; action keys are domain-separated | Post-review 2026-07-04: the signed payload binds `newly_flipped_ids`, which previously survived only in the unsigned outbox event, so a DB-only forensics verifier could not recompute it — migration 0005 persists `quarantine_actions.newly_flipped_ids`. And action signing moved to a disjoint keyspace (`recant-dev-action:{actor}` via `dev_action_signer_for`) so an unauthenticated `actor` string can never forge a signature that verifies under an agent's belief-chain pubkey. Pinning `actor` to a KMS key ARN registry is W4. |
| 15 | One clock domain for the contamination window | Post-review 2026-07-04: `beliefs.created_at` was the gateway host wall clock while `sources.created_at` is the DB `now()`; the window compares the two, so host/DB skew shifted the boundary. The gateway now stamps `created_at` from the DB clock (`SELECT now()` inside the txn), matching the source timestamp. |
| 16 | Closure incompleteness is two distinct signals | Post-review 2026-07-04: `capped` conflated the 10-round runaway guard with adaptive-K truncation at `max_k`, and the operator log misattributed the cause. Split into `rounds_capped` / `knn_truncated`, logged distinctly, exposed in `ClosureOut`. Inferred-edge parent is now the highest-similarity probe per hit (was first-in-scan-order). Retracted kNN hits still stop implicit traversal (asymmetric with the explicit path) — not demo-reachable in W2 (no retract API); revisit when a retract path ships. |

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

## Week 2 verification (Jul 3)

- Design doc `docs/plans/2026-07-03-week2.md`; pre-implementation adversarial
  review (3 lenses) produced 14 findings, all triaged: 2 blocking fixed before
  they could bite (cosine opclass, embedder/threshold mismatch — both also
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
  (self-verifying action rows via migration 0005; domain-separated action keys —
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

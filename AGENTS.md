# Recant contributor instructions

## Project contract

Recant is a custody, provenance, retraction, and action-authorization layer for
shared agent memory. Preserve these boundaries in every change:

- `services/attest_gateway/` is the only supported belief write path.
- `services/quarantine/` owns recant and quarantine state transitions.
- `services/guard/` is the action boundary. A consequential tool call requires
  a valid decision and a freshly consumed exact-argument permit.
- `services/forensics/` is read-only except for signed custody checkpoints and
  evidence archives.
- `memory_events` is the append-only outbox. Delivery state belongs in
  `fanout_deliveries`.
- CockroachDB is the source of truth. Working memory is a disposable copy.

## Security invariants

- Keep every application query tenant-scoped and use `run_tenant_txn` for
  authenticated requests. Row-level security is defense in depth, not a reason
  to omit the predicate.
- Never let a child belief gain authority. Its rank is the minimum of all
  direct sources and parents, and its origins are their union.
- Reconstruct canonical signed payloads from stored fields before trusting
  beliefs, source assertions, receipts, decisions, permits, or checkpoints.
- Use the database clock for values that enter signed payloads or transactional
  time comparisons.
- Production must fail closed for bearer auth, tenant RLS, provenance, KMS
  signing, webhook authentication, and external checkpoint publication.
- Never log, commit, or print `.env`, cloud database URLs, bearer tokens, AWS
  credentials, webhook secrets, or private key material.
- Never run integration tests, seeders, cleanup scripts, or scale tests against
  a cloud or valuable database. The test suite deletes rows.

## Change conventions

- Add schema changes as the next numbered file in `db/migrations/`. Do not edit
  an already released migration to change deployed behavior.
- Keep signed formats versioned and deterministic. Add compatibility handling
  before changing a payload that existing rows may use.
- Preserve serializable retry behavior and idempotency for retryable mutations.
- Keep idempotent response bodies authenticated and encrypted; they can contain
  one-use Guard permits.
- Validate external event payloads against the tenant outbox before applying
  an eviction.
- Before any console or UX change, read
  `.agents/skills/recant-frontend/SKILL.md` in full and follow it.
- Keep changes focused. Do not overwrite unrelated work in a dirty worktree.

## Verification

Use the smallest relevant checks while iterating, then run the full gate before
shipping a cross-cutting change:

```bash
uv run ruff check services agent fanout fleet tests ops recant_client.py
uv run mypy services agent fanout fleet recant_client.py
DATABASE_URL='postgresql://root@localhost:26257/recant?sslmode=disable' uv run pytest
uv run pip-audit
cd console && npm ci && npm audit --audit-level=high && npm run build
```

Start the disposable three-node database with `bash ops/chaos/init.sh` and apply
migrations with `uv run python -m db.migrate`. A fresh-install migration check
is required when migrations change. Inspect `git diff`, run `git diff --check`,
and scan tracked changes for secrets before committing or pushing.

## How to ask Codex for work

A strong task states the outcome, relevant area, constraints, and proof of
completion. Examples:

- `Diagnose why permit consumption returns 409. Do not modify files. Cite the failing path.`
- `Implement tenant-safe receipt listing. Preserve API compatibility, add regression tests, and run the full gate.`
- `Review this branch for security and concurrency bugs. Report findings first; do not push.`
- `Fix the approved findings, update docs, commit, push, and report the commit and checks.`

Codex can inspect and edit this workspace, run local commands, and use the
repository tests. State explicitly when a task may mutate cloud resources,
delete data, deploy, commit, or push. Those permissions are not inferred from a
request to review or diagnose.

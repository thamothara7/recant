# Skills setup

Recant is built with two sets of Claude Code skills. This document records how they
are installed so the setup is reproducible, and maps the CockroachDB Agent Skills to
the milestones where Recant invokes them (spec sections 2 and 4).

## 1. recant-frontend (project skill)

The console design system. It lives in the repo and travels with it, so any session
launched from the project root discovers it and Week 5 console work is governed by it.

- Location: `.claude/skills/recant-frontend/SKILL.md` (committed).
- Source of truth for edits: this file. The loose `recant-frontend.skill` and
  `recant-frontend-SKILL.md` at the repo root are gitignored working copies.
- Invocation: automatic when writing any `console/` frontend code, or manually via
  the Skill tool as `recant-frontend`.

## 2. CockroachDB Agent Skills (required tool, spec section 2 item 4)

The official skills from https://github.com/cockroachlabs/cockroachdb-skills. They are
development-time tools the coding agent invokes (schema review, statement profiling,
transaction design); they are not a runtime component of the product, so they are
installed at user level rather than vendored into this repo.

### Install (user level, upstream-recommended symlink method)

```bash
git clone https://github.com/cockroachlabs/cockroachdb-skills.git \
  ~/.claude/skills-src/cockroachdb-skills
mkdir -p ~/.claude/skills
ln -s ~/.claude/skills-src/cockroachdb-skills/skills \
  ~/.claude/skills/cockroachdb-skills
```

Update later with `git -C ~/.claude/skills-src/cockroachdb-skills pull`. A restart of
Claude Code is required before newly added skills are discovered.

### Verify

```bash
find -L ~/.claude/skills/cockroachdb-skills -name SKILL.md | wc -l   # expect 34
```

### Skills Recant actually uses, by milestone

| Skill | Family | Recant use | Milestone |
|---|---|---|---|
| `cockroachdb-sql` | query-and-schema-design | Schema design review of `db/migrations/*.sql`; CockroachDB-specific SQL for the taint-closure recursive CTE | W1 (done), W2 |
| `profiling-statement-fingerprints` | observability-and-diagnostics | Statement/performance profiling of the taint-closure and vector kNN queries | W2 |
| `designing-application-transactions` | application-development | Validate the serializable write path and the SQLSTATE 40001 retry design | W1 review, W2 quarantine txn |
| `analyzing-schema-change-storage-risk` | observability-and-diagnostics | Estimate backfill cost before the belief vector index | W1/W2 |
| `auditing-table-statistics` | observability-and-diagnostics | Keep optimizer stats fresh for taint queries at seed scale | W2, W6 |
| `configuring-audit-logging` | security-and-governance | The MCP read-only audit-log custody story shown in the demo | W3 |
| `setting-up-local-cluster` | onboarding-and-migrations | Cross-check the local chaos cluster against upstream guidance | W1 (done) |

The two skills the spec explicitly requires (schema design review, statement/performance
profiling) map to `cockroachdb-sql` and `profiling-statement-fingerprints`. Every
invocation and its before/after outcome is recorded in `agent-skills-log.md`.

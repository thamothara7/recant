# CockroachDB Agent Skills Log

Log of invocations of the CockroachDB Agent Skills repo (https://github.com/cockroachlabs/cockroachdb-skills) against this project, per spec section 4 (doubles as the optional tool-feedback submission item). Install steps and the full skill-to-milestone map are in `skills-setup.md`.

| Date | Skill invoked | Target | Finding | Change made |
|------|----------------|--------|---------|-------------|
| 2026-07-03 | (install) 34 skills via user-level symlink | `~/.claude/skills/cockroachdb-skills` | Installed and discoverable; both spec-required skills present (`cockroachdb-sql`, `profiling-statement-fingerprints`) | Recorded in `skills-setup.md`; invocations below |
| pending | `cockroachdb-sql` (schema design review) | `db/migrations/0001_schema.sql` (sources, agents, beliefs, derivations, incidents, quarantine_actions, memory_events) | pending | pending |
| pending | `profiling-statement-fingerprints` (statement/performance profiling) | Taint-closure queries (recursive CTE over `derivations` + vector kNN) | pending (Week 2, taint queries) | pending |
| pending | `designing-application-transactions` | attest-gateway write path + SQLSTATE 40001 retry (`services/common/db.py`) | pending | pending |

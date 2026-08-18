# CockroachDB Agent Skills Log

Evidence log for the CockroachDB Agent Skills repo
(https://github.com/cockroachlabs/cockroachdb-skills). Install steps and the
skill-to-milestone map are in `skills-setup.md`.

**Submission status as of 2026-08-18:** installation is verified, but this file
does not contain completed invocation findings. Recant therefore does not claim
Agent Skills as one of its two submitted CockroachDB tools. Pending rows below
are future work, not submission evidence.

| Date | Skill invoked | Target | Finding | Change made |
|------|----------------|--------|---------|-------------|
| 2026-07-03 | (install) 34 skills via user-level symlink | `~/.claude/skills/cockroachdb-skills` | Installed and discoverable; both spec-required skills present (`cockroachdb-sql`, `profiling-statement-fingerprints`) | Recorded in `skills-setup.md`; invocations below |
| pending | `cockroachdb-sql` (schema design review) | `db/migrations/0001_schema.sql` (sources, agents, beliefs, derivations, incidents, quarantine_actions, memory_events) | pending | pending |
| pending | `profiling-statement-fingerprints` (statement/performance profiling) | Taint-closure queries (recursive CTE over `derivations` + vector kNN) | pending (Week 2, taint queries) | pending |
| pending | `designing-application-transactions` | attest-gateway write path + SQLSTATE 40001 retry (`services/common/db.py`) | pending | pending |

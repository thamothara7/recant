"""Read-only SQL over CockroachDB, the safe surface the Investigator agent uses.

This mirrors the contract of the CockroachDB Cloud Managed MCP Server: the agent
may only READ the memory, never mutate it, and every query is audit-logged. The
safety is defense in depth:

1. A statement allowlist: the first keyword must be SELECT / WITH / SHOW /
   EXPLAIN / TABLE / VALUES, and only one statement is allowed (no stacked
   writes after a semicolon).
2. The query runs inside a `SET TRANSACTION READ ONLY` transaction, so even a
   write that somehow passed the allowlist is rejected by CockroachDB itself.
3. Rows are capped and wide/opaque columns (embeddings, raw bytes) are truncated
   so a result can never blow up the model context or leak vector internals.

In production the same read-only surface is the Managed MCP Server; locally it
is a direct read-only connection with identical guarantees, so the agent code
does not change between the two.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import psycopg

from services.common.db import get_pool
from services.common.logging import configure

log = configure("agent.readonly_sql")

_ALLOWED_FIRST = {"select", "with", "show", "explain", "table", "values"}

# Columns that are huge or opaque; the agent never needs their raw bytes.
_TRUNCATE_COLS = {"embedding"}
_MAX_CELL = 200


class UnsafeQuery(ValueError):
    """The query is not a single read-only statement."""


def validate(sql: str) -> str:
    """Return the normalized query or raise UnsafeQuery. Read-only, one statement."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise UnsafeQuery("empty query")
    if ";" in stripped:
        raise UnsafeQuery("only a single statement is allowed (no ';')")
    first = stripped.split(None, 1)[0].lower()
    if first not in _ALLOWED_FIRST:
        raise UnsafeQuery(
            f"only read-only queries are allowed (SELECT/WITH/SHOW/EXPLAIN/TABLE/"
            f"VALUES); got {first!r}"
        )
    return stripped


def _cell(name: str, value: Any) -> Any:
    if name in _TRUNCATE_COLS and value is not None:
        return "<vector omitted>"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()[:_MAX_CELL]
    if isinstance(value, str) and len(value) > _MAX_CELL:
        return value[:_MAX_CELL] + "..."
    return value


class ReadOnlySQL:
    """Execute one read-only query and return rows as JSON-ready dicts."""

    def __init__(
        self,
        *,
        conn_factory: Callable[[], Any] | None = None,
        max_rows: int = 100,
    ) -> None:
        # conn_factory is an injection seam for tests; production pulls from the pool.
        self._conn_factory = conn_factory
        self.max_rows = max_rows

    def run(self, sql: str) -> dict:
        """Validate, execute read-only, audit-log, and return {columns, rows, truncated}."""
        query = validate(sql)
        log.info("agent read query", extra={"fields": {"sql": query[:500]}})

        if self._conn_factory is not None:
            return self._execute(self._conn_factory(), query)
        with get_pool().connection() as conn:
            return self._execute(conn, query)

    def _execute(self, conn: psycopg.Connection, query: str) -> dict:
        with conn.transaction():
            # DB-enforced read-only: rejects any write even if the allowlist is bypassed.
            conn.execute("SET TRANSACTION READ ONLY")
            cur = conn.execute(query)
            cols = [d.name for d in cur.description] if cur.description else []
            raw = cur.fetchmany(self.max_rows + 1)
        truncated = len(raw) > self.max_rows
        rows = [
            {c: _cell(c, v) for c, v in zip(cols, r)} for r in raw[: self.max_rows]
        ]
        log.info(
            "agent read result",
            extra={"fields": {"rows": len(rows), "truncated": truncated}},
        )
        return {"columns": cols, "rows": rows, "truncated": truncated}

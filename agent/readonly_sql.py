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

import math
import os
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

import psycopg
from psycopg import sql as psycopg_sql

from services.common.db import get_pool, tenant_role_name, tenant_roles_enabled
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


def _json_ready(value: Any) -> Any:
    """Convert psycopg values into Bedrock tool-result document values."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return value if len(value) <= _MAX_CELL else value[:_MAX_CELL] + "..."
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()[:_MAX_CELL]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    # Keep the tool boundary total for less common psycopg adapters (inet,
    # ranges, enums) instead of letting boto3 serialization fail later.
    return str(value)


def _cell(name: str, value: Any) -> Any:
    if name in _TRUNCATE_COLS and value is not None:
        return "<vector omitted>"
    return _json_ready(value)


class ReadOnlySQL:
    """Execute one read-only query and return rows as JSON-ready dicts."""

    def __init__(
        self,
        *,
        conn_factory: Callable[[], Any] | None = None,
        max_rows: int = 100,
        tenant_id: UUID | None = None,
    ) -> None:
        # conn_factory is an injection seam for tests; production pulls from the pool.
        self._conn_factory = conn_factory
        self.max_rows = max_rows
        configured_tenant = os.environ.get("RECANT_TENANT_ID")
        try:
            self.tenant_id = tenant_id or (UUID(configured_tenant) if configured_tenant else None)
        except ValueError as exc:
            raise RuntimeError("RECANT_TENANT_ID must be a UUID") from exc
        if tenant_roles_enabled() and self.tenant_id is None:
            raise RuntimeError("RECANT_TENANT_ID is required when database RLS is enabled")

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
            if tenant_roles_enabled():
                assert self.tenant_id is not None
                conn.execute(
                    psycopg_sql.SQL("SET LOCAL ROLE {}").format(
                        psycopg_sql.Identifier(tenant_role_name(self.tenant_id))
                    )
                )
            cur = conn.execute(query)
            cols = [d.name for d in cur.description] if cur.description else []
            raw = cur.fetchmany(self.max_rows + 1)
        truncated = len(raw) > self.max_rows
        rows = [
            {c: _cell(c, v) for c, v in zip(cols, r, strict=True)} for r in raw[: self.max_rows]
        ]
        log.info(
            "agent read result",
            extra={"fields": {"rows": len(rows), "truncated": truncated}},
        )
        return {"columns": cols, "rows": rows, "truncated": truncated}

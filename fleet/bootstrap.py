"""Working-memory bootstrap on langchain-cockroachdb (W3 plan section 3).

The agent_memory table is a package-bootstrapped runtime cache, NOT part of the
numbered migration chain: its columns belong to langchain-cockroachdb, and
freezing its DDL in our chain would break the chain on any package upgrade.
The bootstrap is idempotent; the shape test pins the exact columns the
eviction SQL and fleet.show touch, so an upgrade that moves one fails the
suite loudly.

Two spike findings (2026-07-10) are load-bearing here:
- NullPool: the package's sync wrappers run each call in a fresh event loop,
  and pooled asyncpg connections are bound to the loop that created them; a
  pooled engine dies with "attached to a different loop" on the second call.
- The vector index DDL is OURS: CSPANNIndex omits the opclass, and on
  CockroachDB a bare index serves only L2 while the package queries cosine
  (`<=>`), which full-scans (the W2 decision-8 lesson, verbatim). The
  namespace-prefixed cosine index below plans as `vector search` for the
  package's exact query shape; verified by EXPLAIN in the shape test.
"""

from __future__ import annotations

import os
from functools import lru_cache
from uuid import UUID

import psycopg
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from langchain_cockroachdb import (
    CockroachDBChatMessageHistory,
    CockroachDBEngine,
    CockroachDBVectorStore,
    DistanceStrategy,
)

from fleet.embeddings import LangChainEmbedder
from services.common.embedder import DIMENSIONS

TABLE = "agent_memory"
NAMESPACE_COLUMN = "agent_id"
INDEX_DDL = (
    f"CREATE VECTOR INDEX IF NOT EXISTS {TABLE}_embedding_idx"
    f" ON {TABLE} ({NAMESPACE_COLUMN}, embedding vector_cosine_ops)"
)


def engine_url(database_url: str | None = None) -> str:
    """postgresql://...?sslmode=disable -> cockroachdb+asyncpg://...

    Scheme swap only, params dropped: asyncpg rejects sslmode and the insecure
    local cluster needs no TLS arguments. TLS params return with U1 (Cloud).
    """
    url = database_url or os.environ["DATABASE_URL"]
    return url.split("?")[0].replace("postgresql://", "cockroachdb+asyncpg://", 1)


@lru_cache(maxsize=1)
def get_engine() -> CockroachDBEngine:
    return CockroachDBEngine.from_engine(create_async_engine(engine_url(), poolclass=NullPool))


def ensure_agent_memory() -> None:
    """Idempotent: package-owned table plus our cosine vector index."""
    get_engine().init_vectorstore_table(TABLE, DIMENSIONS, namespace_column=NAMESPACE_COLUMN)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(INDEX_DDL)


def store_for(agent_id: UUID | str) -> CockroachDBVectorStore:
    """One store per agent over the single shared table: the namespace column
    scopes retrieval, the shared table keeps eviction a one-statement DELETE."""
    return CockroachDBVectorStore(
        get_engine(),
        LangChainEmbedder(),
        TABLE,
        namespace_column=NAMESPACE_COLUMN,
        namespace=str(agent_id),
        distance_strategy=DistanceStrategy.COSINE,
    )


def history_for(agent_name: str) -> CockroachDBChatMessageHistory:
    """Per-agent transcript. Eviction never writes here (plan section 3): the
    transcript is the agent's own record; the visible proof of eviction is the
    context-assembly diff plus the receipt event."""
    history = CockroachDBChatMessageHistory(session_id=agent_name, engine=get_engine().engine)
    history.create_table_if_not_exists()
    return history


def reset_runtime() -> None:
    """Clear working memory, actions, transcripts, and delivery ledger.
    NEVER custody rows (beliefs, derivations, incidents, events stay)."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for table in ("fanout_deliveries", "agent_actions"):
            conn.execute(f"DELETE FROM {table}")
        for table in (TABLE, "message_store"):
            if conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]:
                conn.execute(f"DELETE FROM {table}")

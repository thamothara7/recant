"""Connection pool and transaction retry policy.

CockroachDB aborts contending serializable transactions with SQLSTATE 40001 and
expects the client to retry with backoff (spec section 9).
"""

import os
import random
import time
from typing import Callable, TypeVar

import psycopg
from psycopg_pool import ConnectionPool

T = TypeVar("T")

MAX_RETRIES = 8

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # check= validates each connection at checkout and transparently
        # replaces dead ones, so a long-running service survives a database
        # restart (node kill, ops/chaos/reset.sh) without a bounce. Without it,
        # every pooled connection that died with the old server produces one
        # 500 before the pool heals; seen live 2026-07-16.
        _pool = ConnectionPool(
            os.environ["DATABASE_URL"],
            min_size=1,
            max_size=10,
            check=ConnectionPool.check_connection,
        )
    return _pool


def retry_serialization(
    fn: Callable[[], T],
    *,
    max_retries: int = MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    last: psycopg.errors.SerializationFailure | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except psycopg.errors.SerializationFailure as exc:
            last = exc
            if attempt < max_retries - 1:
                sleep(min(0.025 * (2**attempt), 1.0) * (0.5 + random.random()))
    assert last is not None
    raise last


def run_txn(fn: Callable[[psycopg.Connection], T]) -> T:
    """Run fn inside one serializable transaction, retrying on 40001."""

    def attempt() -> T:
        with get_pool().connection() as conn:
            with conn.transaction():
                return fn(conn)

    return retry_serialization(attempt)

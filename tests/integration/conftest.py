"""Integration tests need a real CockroachDB reachable via DATABASE_URL
(start one with ops/chaos/init.sh). They are skipped otherwise."""

import os

import pytest

requires_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="integration tests need DATABASE_URL pointing at a CockroachDB cluster",
)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from db.migrate import main as migrate

    migrate()
    from services.attest_gateway.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def forensics_client():
    from fastapi.testclient import TestClient

    from services.forensics.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def quarantine_client():
    from fastapi.testclient import TestClient

    from services.quarantine.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_tables():
    if not os.environ.get("DATABASE_URL"):
        yield
        return
    from services.common.db import get_pool

    with get_pool().connection() as conn:
        # FK order: fanout_deliveries references memory_events; agent_actions
        # references agents and incidents. agent_memory and message_store are
        # runtime tables bootstrapped outside the migration chain, so they may
        # not exist yet.
        for table in (
            "fanout_deliveries",
            "agent_actions",
            "derivations",
            "beliefs",
            "quarantine_actions",
            "incidents",
            "agents",
            "sources",
            "memory_events",
        ):
            conn.execute(f"DELETE FROM {table}")
        for table in ("agent_memory", "message_store"):
            if conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]:
                conn.execute(f"DELETE FROM {table}")
    yield

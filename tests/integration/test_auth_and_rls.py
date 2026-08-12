"""Authentication, application RBAC, and database-enforced tenant isolation."""

from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Json

from tests.integration.conftest import requires_db

pytestmark = requires_db


def _principal(token: str, tenant_id, subject: str, roles: list[str]):
    from services.common.auth import token_digest
    from services.common.db import run_txn

    principal_id = uuid4()
    run_txn(
        lambda conn: conn.execute(
            "INSERT INTO api_principals"
            " (principal_id, tenant_id, subject, token_hash, roles)"
            " VALUES (%s, %s, %s, %s, %s)",
            (principal_id, tenant_id, subject, token_digest(token), roles),
        )
    )
    return principal_id


def test_required_auth_and_source_authority_rbac(client, monkeypatch):
    from services.common.auth import DEFAULT_TENANT_ID

    monkeypatch.setenv("RECANT_AUTH_MODE", "required")
    _principal("writer-secret", DEFAULT_TENANT_ID, "writer", ["writer"])
    _principal("admin-secret", DEFAULT_TENANT_ID, "source-admin", ["source_admin"])

    assert client.post("/agents", json={"name": "no-token"}).status_code == 401

    writer_headers = {"Authorization": "Bearer writer-secret"}
    created = client.post("/agents", json={"name": "authenticated"}, headers=writer_headers)
    assert created.status_code == 201, created.text
    elevated = client.post(
        "/sources",
        json={"kind": "api", "uri": "https://example.com", "trust_tier": "verified"},
        headers=writer_headers,
    )
    assert elevated.status_code == 403

    admin = client.post(
        "/sources",
        json={"kind": "api", "uri": "https://vendor.example", "trust_tier": "verified"},
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert admin.status_code == 201, admin.text
    assert admin.json()["authority_rank"] == 60
    assert admin.json()["issuer"] == "source-admin"


def test_rls_blocks_cross_tenant_rows_even_without_query_predicate():
    from services.common.auth import DEFAULT_TENANT_ID
    from services.common.db import run_txn, tenant_role_name

    tenant_id = uuid4()
    tenant_role = tenant_role_name(tenant_id)
    own_source, foreign_source = uuid4(), uuid4()

    def setup(conn):
        conn.execute(
            "INSERT INTO tenants (tenant_id, slug, display_name) VALUES (%s, %s, %s)",
            (tenant_id, f"rls-{tenant_id}", "RLS test"),
        )
        conn.execute(
            "INSERT INTO sources (source_id, tenant_id, kind, uri, trust_tier)"
            " VALUES (%s, %s, 'test', 'https://own.example', 'untrusted'),"
            " (%s, %s, 'test', 'https://foreign.example', 'untrusted')",
            (own_source, tenant_id, foreign_source, DEFAULT_TENANT_ID),
        )
        conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(tenant_role)))
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(tenant_role))
        )
        conn.execute(
            sql.SQL("GRANT SELECT ON TABLE sources TO {}").format(sql.Identifier(tenant_role))
        )

    run_txn(setup)
    try:

        def isolated_read(conn):
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(tenant_role)))
            return conn.execute("SELECT source_id FROM sources ORDER BY source_id").fetchall()

        rows = run_txn(isolated_read)
        assert rows == [(own_source,)]
    finally:

        def cleanup(conn):
            conn.execute(
                "DELETE FROM sources WHERE source_id IN (%s, %s)",
                (own_source, foreign_source),
            )
            conn.execute("DELETE FROM tenants WHERE tenant_id = %s", (tenant_id,))
            conn.execute(
                sql.SQL("REVOKE SELECT ON TABLE sources FROM {}").format(
                    sql.Identifier(tenant_role)
                )
            )
            conn.execute(
                sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(sql.Identifier(tenant_role))
            )
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(tenant_role)))

        run_txn(cleanup)


def test_runtime_memory_rls_uses_tenant_metadata():
    from fleet.bootstrap import ensure_agent_memory
    from services.common.auth import DEFAULT_TENANT_ID
    from services.common.db import run_txn, tenant_role_name

    ensure_agent_memory()
    tenant_id = uuid4()
    role = tenant_role_name(tenant_id)
    own_memory, foreign_memory, forged_memory = uuid4(), uuid4(), uuid4()

    def setup(conn):
        conn.execute(
            "INSERT INTO tenants (tenant_id, slug, display_name) VALUES (%s, %s, 'Memory RLS')",
            (tenant_id, f"memory-rls-{tenant_id}"),
        )
        conn.execute(
            "INSERT INTO agent_memory (id, agent_id, metadata) VALUES"
            " (%s, 'own-agent', %s), (%s, 'foreign-agent', %s)",
            (
                own_memory,
                Json({"tenant_id": str(tenant_id)}),
                foreign_memory,
                Json({"tenant_id": str(DEFAULT_TENANT_ID)}),
            ),
        )
        conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        conn.execute(
            sql.SQL("GRANT SELECT, INSERT ON TABLE agent_memory TO {}").format(sql.Identifier(role))
        )

    run_txn(setup)
    try:

        def isolated_read(conn):
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            return conn.execute("SELECT id FROM agent_memory ORDER BY id").fetchall()

        assert run_txn(isolated_read) == [(own_memory,)]

        def forged_insert(conn):
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            conn.execute(
                "INSERT INTO agent_memory (id, agent_id, metadata) VALUES (%s, 'forged', %s)",
                (forged_memory, Json({"tenant_id": str(DEFAULT_TENANT_ID)})),
            )

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            run_txn(forged_insert)
    finally:

        def cleanup(conn):
            conn.execute(
                "DELETE FROM agent_memory WHERE id IN (%s, %s, %s)",
                (own_memory, foreign_memory, forged_memory),
            )
            conn.execute("DELETE FROM tenants WHERE tenant_id = %s", (tenant_id,))
            conn.execute(
                sql.SQL("REVOKE SELECT, INSERT ON TABLE agent_memory FROM {}").format(
                    sql.Identifier(role)
                )
            )
            conn.execute(
                sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(sql.Identifier(role))
            )
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))

        run_txn(cleanup)

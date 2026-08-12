"""Provision one tenant, SQL RLS role, and initial API principal.

Run this with an administrative DATABASE_URL after migrations. The plaintext API
token is printed exactly once; CockroachDB stores only its SHA-256 digest.
"""

from __future__ import annotations

import argparse
import os
import secrets
from uuid import uuid4

import psycopg
from psycopg import sql

from services.common.auth import ALL_ROLES, token_digest
from services.common.db import tenant_role_name

TENANT_TABLES = (
    "sources",
    "agents",
    "beliefs",
    "derivations",
    "incidents",
    "quarantine_actions",
    "memory_events",
    "fanout_deliveries",
    "agent_actions",
    "context_receipts",
    "tool_policies",
    "action_decisions",
    "action_confirmations",
    "action_permits",
    "semantic_relations",
    "idempotency_records",
    "custody_checkpoints",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="provision a Recant tenant")
    parser.add_argument("slug")
    parser.add_argument("--display-name")
    parser.add_argument("--subject", default="owner")
    parser.add_argument(
        "--roles",
        default=",".join(sorted(ALL_ROLES)),
        help="comma-separated application roles",
    )
    parser.add_argument(
        "--app-db-role",
        required=True,
        help="non-admin SQL role used by the Recant services",
    )
    args = parser.parse_args()
    roles = sorted({role.strip() for role in args.roles.split(",") if role.strip()})
    unknown = set(roles) - ALL_ROLES
    if unknown:
        parser.error(f"unknown roles: {', '.join(sorted(unknown))}")
    tenant_id = uuid4()
    principal_id = uuid4()
    token = f"rct_{secrets.token_urlsafe(32)}"
    tenant_role = tenant_role_name(tenant_id)

    # CockroachDB supports transactional schema changes, so tenant metadata,
    # SQL role creation, and grants either all commit or all roll back.
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(
            "INSERT INTO tenants (tenant_id, slug, display_name) VALUES (%s, %s, %s)",
            (tenant_id, args.slug, args.display_name or args.slug),
        )
        conn.execute(
            "INSERT INTO api_principals"
            " (principal_id, tenant_id, subject, token_hash, roles)"
            " VALUES (%s, %s, %s, %s, %s)",
            (principal_id, tenant_id, args.subject, token_digest(token), roles),
        )
        conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(tenant_role)))
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(tenant_role))
        )
        for table in TENANT_TABLES:
            conn.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                    sql.Identifier(table), sql.Identifier(tenant_role)
                )
            )
        agent_memory_row = conn.execute("SELECT to_regclass('agent_memory')").fetchone()
        if agent_memory_row is not None and agent_memory_row[0]:
            conn.execute("ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY")
            conn.execute(
                "CREATE POLICY IF NOT EXISTS agent_memory_tenant_policy"
                " ON agent_memory FOR ALL TO PUBLIC"
                " USING (current_user() = 'recant_t_' ||"
                " replace(metadata->>'tenant_id', '-', ''))"
                " WITH CHECK (current_user() = 'recant_t_' ||"
                " replace(metadata->>'tenant_id', '-', ''))"
            )
            conn.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE agent_memory TO {}").format(
                    sql.Identifier(tenant_role)
                )
            )
        conn.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(tenant_role), sql.Identifier(args.app_db_role)
            )
        )
        conn.execute(
            sql.SQL("GRANT SELECT ON TABLE tenants, api_principals TO {}").format(
                sql.Identifier(args.app_db_role)
            )
        )

    print(f"tenant_id={tenant_id}")
    print(f"tenant_sql_role={tenant_role}")
    print(f"principal_id={principal_id}")
    print(f"api_token={token}")
    print("Store api_token in a secret manager. It cannot be recovered from the database.")


if __name__ == "__main__":
    main()

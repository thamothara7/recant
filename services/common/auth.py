"""Bearer-token authentication and application-level RBAC.

Development mode is deliberately backward compatible: when authentication is
disabled, requests receive a synthetic principal scoped to the stable local
tenant. Production defaults to required authentication and never falls back.
Tokens are random secrets; only SHA-256 digests are stored in CockroachDB.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from fastapi import Depends, Header, HTTPException

from services.common.db import run_txn

DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
ALL_ROLES = frozenset({"writer", "source_admin", "operator", "auditor", "policy_admin"})


@dataclass(frozen=True)
class Principal:
    principal_id: UUID | None
    tenant_id: UUID
    subject: str
    roles: frozenset[str]
    development: bool = False

    @property
    def key(self) -> str:
        return str(self.principal_id) if self.principal_id else f"dev:{self.subject}"

    def has_any(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


DEV_PRINCIPAL = Principal(
    principal_id=None,
    tenant_id=DEFAULT_TENANT_ID,
    subject="development",
    roles=ALL_ROLES,
    development=True,
)


def auth_required() -> bool:
    mode = os.environ.get("RECANT_AUTH_MODE")
    normalized = mode.strip().lower() if mode is not None else None
    if normalized not in {None, "disabled", "required"}:
        raise RuntimeError("RECANT_AUTH_MODE must be 'disabled' or 'required'")
    # Production is a security boundary, not merely a set of defaults. A stale
    # development .env must not be able to turn authentication back off.
    if os.environ.get("RECANT_ENV", "").strip().lower() == "production":
        return True
    return normalized == "required"


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def authenticate(authorization: str | None = Header(default=None)) -> Principal:
    if not auth_required():
        return DEV_PRINCIPAL
    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="a bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = token.strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="a bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def txn(conn):
        return conn.execute(
            "SELECT p.principal_id, p.tenant_id, p.subject, p.roles"
            " FROM api_principals p JOIN tenants t ON t.tenant_id = p.tenant_id"
            " WHERE p.token_hash = %s AND p.active AND t.active",
            (token_digest(token),),
        ).fetchone()

    row = run_txn(txn)
    if row is None:
        raise HTTPException(
            status_code=401,
            detail="invalid or inactive bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Principal(
        principal_id=row[0],
        tenant_id=row[1],
        subject=row[2],
        roles=frozenset(row[3] or []),
    )


def require_roles(*allowed: str) -> Callable[..., Principal]:
    if not allowed:
        raise ValueError("at least one role is required")

    def dependency(principal: Principal = Depends(authenticate)) -> Principal:
        if not principal.has_any(*allowed):
            raise HTTPException(
                status_code=403,
                detail=f"one of these roles is required: {', '.join(sorted(allowed))}",
            )
        return principal

    return dependency

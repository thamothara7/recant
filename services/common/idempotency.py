"""Transactional Idempotency-Key support for mutating HTTP endpoints."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from datetime import timedelta
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from psycopg.types.json import Json

from services.common.attestation import canonical_json

_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_ENCRYPTION_VERSION = "aesgcm-v1"
_DEV_ENCRYPTION_KEY = hashlib.sha256(b"recant-development-idempotency-key-v1").digest()


def _production() -> bool:
    return os.environ.get("RECANT_ENV", "").strip().lower() == "production"


def _encryption_key() -> bytes:
    encoded = os.environ.get("RECANT_IDEMPOTENCY_ENCRYPTION_KEY")
    if not encoded:
        if _production():
            raise RuntimeError(
                "RECANT_IDEMPOTENCY_ENCRYPTION_KEY is required for production idempotency"
            )
        return _DEV_ENCRYPTION_KEY
    try:
        if re.fullmatch(r"[0-9a-fA-F]{64}", encoded):
            key = bytes.fromhex(encoded)
        else:
            key = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            )
    except (ValueError, TypeError, binascii.Error) as exc:
        raise RuntimeError(
            "RECANT_IDEMPOTENCY_ENCRYPTION_KEY must encode exactly 32 bytes"
        ) from exc
    if len(key) != 32:
        raise RuntimeError("RECANT_IDEMPOTENCY_ENCRYPTION_KEY must encode exactly 32 bytes")
    return key


def _aad(
    *,
    tenant_id: UUID,
    principal_key: str,
    method: str,
    path: str,
    key: str,
    digest: bytes,
) -> bytes:
    return canonical_json(
        {
            "type": "recant.idempotency-response.v1",
            "tenant_id": tenant_id,
            "principal_key": principal_key,
            "method": method,
            "path": path,
            "idempotency_key": key,
            "request_hash": digest.hex(),
        }
    )


def _seal_response(response_body: dict, *, aad: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(
        nonce,
        canonical_json(response_body),
        aad,
    )
    return ciphertext, nonce


def _open_response(ciphertext: bytes, nonce: bytes, *, aad: bytes) -> dict:
    try:
        plaintext = AESGCM(_encryption_key()).decrypt(nonce, ciphertext, aad)
        value = json.loads(plaintext)
    except (InvalidTag, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("stored idempotency response failed authentication") from exc
    if not isinstance(value, dict):
        raise RuntimeError("stored idempotency response is not an object")
    return value


def validate_key(key: str | None) -> str | None:
    if key is None:
        return None
    if not _KEY.fullmatch(key):
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must be 8 to 128 URL-safe characters",
        )
    return key


def request_hash(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(canonical_json(value)).digest()


def replay(
    conn,
    *,
    tenant_id: UUID,
    principal_key: str,
    method: str,
    path: str,
    key: str | None,
    digest: bytes,
) -> dict | None:
    """Atomically claim a key or return its committed response.

    The placeholder and the protected mutation live in the same transaction.
    A concurrent request blocks on the primary key and then receives the first
    transaction's final response instead of performing the mutation twice.
    Expired rows are reclaimed immediately, without waiting for row-level TTL.
    """
    if key is None:
        return None
    row = conn.execute(
        "INSERT INTO idempotency_records"
        " (tenant_id, principal_key, method, path, idempotency_key, request_hash,"
        " response_status, response_body, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, 0, %s, now() + %s)"
        " ON CONFLICT (tenant_id, principal_key, method, path, idempotency_key)"
        " DO UPDATE SET"
        " request_hash = CASE WHEN idempotency_records.expires_at <= now()"
        "   THEN excluded.request_hash ELSE idempotency_records.request_hash END,"
        " response_status = CASE WHEN idempotency_records.expires_at <= now()"
        "   THEN 0 ELSE idempotency_records.response_status END,"
        " response_body = CASE WHEN idempotency_records.expires_at <= now()"
        "   THEN excluded.response_body ELSE idempotency_records.response_body END,"
        " response_ciphertext = CASE WHEN idempotency_records.expires_at <= now()"
        "   THEN NULL ELSE idempotency_records.response_ciphertext END,"
        " response_nonce = CASE WHEN idempotency_records.expires_at <= now()"
        "   THEN NULL ELSE idempotency_records.response_nonce END,"
        " encryption_version = CASE WHEN idempotency_records.expires_at <= now()"
        "   THEN 'none' ELSE idempotency_records.encryption_version END,"
        " created_at = CASE WHEN idempotency_records.expires_at <= now()"
        "   THEN now() ELSE idempotency_records.created_at END,"
        " expires_at = CASE WHEN idempotency_records.expires_at <= now()"
        "   THEN excluded.expires_at ELSE idempotency_records.expires_at END"
        " RETURNING request_hash, response_status, response_body,"
        " response_ciphertext, response_nonce, encryption_version",
        (
            tenant_id,
            principal_key,
            method,
            path,
            key,
            digest,
            Json({}),
            timedelta(hours=24),
        ),
    ).fetchone()
    assert row is not None
    if bytes(row[0]) != digest:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used with a different request",
        )
    if int(row[1]) == 0:
        return None
    if row[5] == _ENCRYPTION_VERSION:
        if row[3] is None or row[4] is None:
            raise RuntimeError("encrypted idempotency response is incomplete")
        return _open_response(
            bytes(row[3]),
            bytes(row[4]),
            aad=_aad(
                tenant_id=tenant_id,
                principal_key=principal_key,
                method=method,
                path=path,
                key=key,
                digest=digest,
            ),
        )
    if row[5] != "none":
        raise RuntimeError(f"unsupported idempotency encryption version: {row[5]}")
    body = row[2]
    return json.loads(body) if isinstance(body, str) else body


def store(
    conn,
    *,
    tenant_id: UUID,
    principal_key: str,
    method: str,
    path: str,
    key: str | None,
    digest: bytes,
    response_status: int,
    response_body: dict,
) -> None:
    if key is None:
        return
    ciphertext, nonce = _seal_response(
        response_body,
        aad=_aad(
            tenant_id=tenant_id,
            principal_key=principal_key,
            method=method,
            path=path,
            key=key,
            digest=digest,
        ),
    )
    completed = conn.execute(
        "UPDATE idempotency_records SET response_status = %s, response_body = %s,"
        " response_ciphertext = %s, response_nonce = %s, encryption_version = %s"
        " WHERE tenant_id = %s AND principal_key = %s AND method = %s AND path = %s"
        " AND idempotency_key = %s AND request_hash = %s AND response_status = 0",
        (
            response_status,
            Json({}),
            ciphertext,
            nonce,
            _ENCRYPTION_VERSION,
            tenant_id,
            principal_key,
            method,
            path,
            key,
            digest,
        ),
    )
    if completed.rowcount != 1:
        raise RuntimeError("idempotency claim was not completed")

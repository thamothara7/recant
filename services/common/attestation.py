"""Canonical JSON and digest helpers shared by signed control-plane records."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID


def _default(value: Any) -> str:
    if isinstance(value, (datetime, UUID)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_default,
    ).encode("utf-8")


def sha256(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)

import base64

import pytest

from services.common import idempotency


def test_production_requires_idempotency_encryption_key(monkeypatch):
    monkeypatch.setenv("RECANT_ENV", "production")
    monkeypatch.delenv("RECANT_IDEMPOTENCY_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="RECANT_IDEMPOTENCY_ENCRYPTION_KEY"):
        idempotency._encryption_key()


def test_idempotency_response_encryption_authenticates_context(monkeypatch):
    key = bytes(range(32))
    monkeypatch.setenv("RECANT_IDEMPOTENCY_ENCRYPTION_KEY", base64.urlsafe_b64encode(key).decode())
    ciphertext, nonce = idempotency._seal_response({"permit": "secret"}, aad=b"tenant-a")

    assert b"secret" not in ciphertext
    assert idempotency._open_response(ciphertext, nonce, aad=b"tenant-a") == {
        "permit": "secret"
    }
    with pytest.raises(RuntimeError, match="failed authentication"):
        idempotency._open_response(ciphertext, nonce, aad=b"tenant-b")

from uuid import UUID

import pytest

from services.common.auth import auth_required, token_digest
from services.common.db import tenant_role_name, tenant_roles_enabled


def test_production_defaults_to_auth_and_database_rls(monkeypatch):
    monkeypatch.setenv("RECANT_ENV", "production")
    monkeypatch.delenv("RECANT_AUTH_MODE", raising=False)
    monkeypatch.delenv("RECANT_DB_RLS", raising=False)
    assert auth_required() is True
    assert tenant_roles_enabled() is True


def test_production_cannot_disable_auth_rls_or_provenance(monkeypatch):
    from services.attest_gateway.app import _provenance_required

    monkeypatch.setenv("RECANT_ENV", " Production ")
    monkeypatch.setenv("RECANT_AUTH_MODE", "disabled")
    monkeypatch.setenv("RECANT_DB_RLS", "false")
    monkeypatch.setenv("RECANT_REQUIRE_PROVENANCE", "off")
    assert auth_required() is True
    assert tenant_roles_enabled() is True
    assert _provenance_required() is True


def test_development_defaults_preserve_local_zero_config(monkeypatch):
    monkeypatch.delenv("RECANT_ENV", raising=False)
    monkeypatch.delenv("RECANT_AUTH_MODE", raising=False)
    monkeypatch.delenv("RECANT_DB_RLS", raising=False)
    assert auth_required() is False
    assert tenant_roles_enabled() is False


def test_invalid_auth_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("RECANT_AUTH_MODE", "maybe")
    with pytest.raises(RuntimeError, match="RECANT_AUTH_MODE"):
        auth_required()


@pytest.mark.parametrize(
    ("variable", "function"),
    [("RECANT_DB_RLS", tenant_roles_enabled)],
)
def test_invalid_security_boolean_fails_closed(monkeypatch, variable, function):
    monkeypatch.setenv(variable, "sometimes")
    with pytest.raises(RuntimeError, match=variable):
        function()


def test_token_storage_is_digest_only_and_role_name_is_injection_safe():
    assert token_digest("secret") != b"secret"
    role = tenant_role_name(UUID("12345678-1234-5678-1234-567812345678"))
    assert role == "recant_t_12345678123456781234567812345678"

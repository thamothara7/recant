import pytest

from services.common.config import cors_origins


def test_cors_origins_are_normalized(monkeypatch):
    monkeypatch.setenv(
        "RECANT_CORS_ORIGINS", " https://console.example.com/,http://localhost:5173 "
    )
    assert cors_origins() == ["https://console.example.com", "http://localhost:5173"]


@pytest.mark.parametrize("value", ["*", " , "])
def test_production_cors_fails_closed_without_exact_origins(monkeypatch, value):
    monkeypatch.setenv("RECANT_ENV", "production")
    monkeypatch.setenv("RECANT_CORS_ORIGINS", value)
    with pytest.raises(RuntimeError, match="exact browser origins"):
        cors_origins()

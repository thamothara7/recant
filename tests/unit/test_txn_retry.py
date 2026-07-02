import psycopg
import pytest

from services.common.db import retry_serialization
from services.common.vectors import to_vector_literal


def test_retries_serialization_failures_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise psycopg.errors.SerializationFailure("restart transaction")
        return "ok"

    assert retry_serialization(fn, sleep=sleeps.append) == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    assert all(s > 0 for s in sleeps)


def test_raises_after_max_retries():
    def fn():
        raise psycopg.errors.SerializationFailure("always")

    with pytest.raises(psycopg.errors.SerializationFailure):
        retry_serialization(fn, max_retries=3, sleep=lambda s: None)


def test_non_retryable_errors_propagate_immediately():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("bug")

    with pytest.raises(ValueError):
        retry_serialization(fn, sleep=lambda s: None)
    assert calls["n"] == 1


def test_vector_literal():
    assert to_vector_literal([0.5, -1.0, 2.25]) == "[0.5,-1.0,2.25]"

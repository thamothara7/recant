"""Helpers for CockroachDB VECTOR values (pgvector-compatible text literals)."""


def to_vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"

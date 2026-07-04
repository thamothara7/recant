"""Shared runtime configuration helpers."""

import os

DEFAULT_CORS_ORIGIN = "http://localhost:5173"


def cors_origins() -> list[str]:
    """Browser origins allowed to read the judge-overlay header cross-origin.

    Split on ',' with whitespace stripped and empties dropped: Starlette's
    CORSMiddleware matches origins by exact string, so a natural value like
    'http://localhost:5173, https://demo.example.com' must not yield a leading
    space that never equals a browser Origin header (review 2026-07-03)."""
    raw = os.environ.get("RECANT_CORS_ORIGINS", DEFAULT_CORS_ORIGIN)
    return [o.strip() for o in raw.split(",") if o.strip()]

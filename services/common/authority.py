"""Stable authority ranks used by provenance and action policy.

Ranks are intentionally sparse so deployments can insert local levels without
rewriting stored records. A derivation inherits the minimum rank across every
supporting source and parent. Text generation can therefore preserve or lower
authority, but it cannot raise it.
"""

from __future__ import annotations

UNKNOWN = 0
EXTERNAL = 10
PUBLIC = 20
AUTHENTICATED_TOOL = 30
PARTNER = 40
USER_HISTORY = 50
VERIFIED = 60
USER_CONFIRMED = 70
SYSTEM = 90

TRUST_TIER_RANK = {
    "untrusted": EXTERNAL,
    "public": PUBLIC,
    "partner": PARTNER,
    "verified": VERIFIED,
}

RANK_LABELS = {
    UNKNOWN: "unknown",
    EXTERNAL: "external",
    PUBLIC: "public",
    AUTHENTICATED_TOOL: "authenticated_tool",
    PARTNER: "partner",
    USER_HISTORY: "user_history",
    VERIFIED: "verified",
    USER_CONFIRMED: "user_confirmed",
    SYSTEM: "system",
}


def rank_for_trust_tier(trust_tier: str) -> int:
    try:
        return TRUST_TIER_RANK[trust_tier]
    except KeyError as exc:
        raise ValueError(f"unknown trust tier: {trust_tier}") from exc


def label_for_rank(rank: int) -> str:
    if rank in RANK_LABELS:
        return RANK_LABELS[rank]
    lower = [value for value in RANK_LABELS if value <= rank]
    return RANK_LABELS[max(lower)] if lower else "unknown"

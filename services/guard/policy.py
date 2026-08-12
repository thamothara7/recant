"""Deterministic tool-risk policy resolution.

MCP annotations can raise risk but never lower it. A trusted operator must
register a policy to treat a tool as read-only; unknown tools fail toward the
effect class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from services.common.authority import EXTERNAL, USER_CONFIRMED, USER_HISTORY

RiskClass = Literal["read", "navigate", "effect", "purchase", "credential"]
PolicySource = Literal["stored", "builtin"]


@dataclass(frozen=True)
class ToolPolicy:
    tool_name: str
    risk_class: RiskClass
    required_authority: int
    confirmation_allowed: bool
    policy_version: str
    source: PolicySource


_BUILTINS: dict[str, tuple[RiskClass, int, bool]] = {
    "read": ("read", EXTERNAL, False),
    "search": ("read", EXTERNAL, False),
    "lookup": ("read", EXTERNAL, False),
    "navigate": ("navigate", USER_HISTORY, True),
    "refund": ("effect", USER_CONFIRMED, True),
    "send_email": ("effect", USER_CONFIRMED, True),
    "purchase": ("purchase", USER_CONFIRMED, True),
    "credential": ("credential", USER_CONFIRMED, True),
}


def resolve_policy(conn, tenant_id, tool_name: str, annotations=None) -> ToolPolicy:
    row = conn.execute(
        "SELECT risk_class, required_authority, confirmation_allowed, policy_version"
        " FROM tool_policies WHERE tenant_id = %s AND tool_name = %s",
        (tenant_id, tool_name),
    ).fetchone()
    if row is not None:
        policy = ToolPolicy(tool_name, row[0], int(row[1]), bool(row[2]), row[3], "stored")
    else:
        base = tool_name.rsplit("/", 1)[-1].rsplit(":", 1)[-1].lower()
        risk, authority, confirmation = _BUILTINS.get(base, ("effect", USER_CONFIRMED, True))
        policy = ToolPolicy(tool_name, risk, authority, confirmation, "builtin-v1", "builtin")

    if (
        annotations is not None
        and annotations.destructive_hint
        and policy.risk_class in {"read", "navigate"}
    ):
        return ToolPolicy(
            tool_name,
            "effect",
            USER_CONFIRMED,
            True,
            f"{policy.policy_version}+destructive-hint",
            policy.source,
        )
    return policy

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _finite_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("action arguments must contain only finite JSON numbers")
    if isinstance(value, dict):
        for item in value.values():
            _finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _finite_json(item)
    return value


class ContextReceiptIn(BaseModel):
    agent_id: UUID
    belief_ids: list[UUID] = Field(min_length=1, max_length=64)
    ttl_seconds: int = Field(default=300, ge=30, le=900)


class ContextReceiptOut(BaseModel):
    receipt_id: UUID
    agent_id: UUID
    belief_ids: list[UUID]
    origin_source_ids: list[UUID]
    authority_rank: int
    authority_label: str
    expires_at: datetime
    sig: str
    signing_algorithm: str
    signer_key_id: str


class ToolAnnotations(BaseModel):
    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None


class AuthorizeIn(BaseModel):
    agent_id: UUID
    tool_name: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:/-]+$")
    arguments: dict[str, Any]
    support_belief_ids: list[UUID] = Field(default_factory=list, max_length=64)
    context_receipt_id: UUID | None = None
    annotations: ToolAnnotations | None = None

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _finite_json(value)


class DecisionOut(BaseModel):
    decision_id: UUID
    agent_id: UUID
    tool_name: str
    arguments: dict[str, Any]
    action_digest: str
    support_belief_ids: list[UUID]
    risk_class: str
    required_authority: int
    required_authority_label: str
    observed_authority: int
    observed_authority_label: str
    decision: Literal["allow", "confirm", "deny"]
    reason: str
    policy_version: str
    created_at: datetime
    supersedes_decision_id: UUID | None = None
    permit: str | None = None
    permit_id: UUID | None = None
    permit_expires_at: datetime | None = None
    sig: str
    signing_algorithm: str
    signer_key_id: str


class ConfirmIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1024)


class ConsumeIn(BaseModel):
    permit: str = Field(min_length=32, max_length=8192)
    tool_name: str = Field(min_length=1, max_length=256)
    arguments: dict[str, Any]

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _finite_json(value)


class ConsumeOut(BaseModel):
    permit_id: UUID
    decision_id: UUID
    action_id: UUID
    consumed_at: datetime
    status: Literal["executed"] = "executed"


class ToolPolicyIn(BaseModel):
    risk_class: Literal["read", "navigate", "effect", "purchase", "credential"]
    required_authority: int = Field(ge=0, le=90)
    confirmation_allowed: bool = True
    policy_version: str = Field(min_length=1, max_length=128)


class ToolPolicyOut(ToolPolicyIn):
    tool_name: str
    source: Literal["stored", "builtin"]


class RelationVerifyIn(BaseModel):
    left_belief_id: UUID
    right_belief_id: UUID


class RelationVerifyOut(BaseModel):
    left_belief_id: UUID
    right_belief_id: UUID
    relation: Literal["equivalent", "entails", "contradicts", "related", "unknown"]
    confidence: float
    evidence_method: str
    evidence_model: str | None = None
    evidence_version: str

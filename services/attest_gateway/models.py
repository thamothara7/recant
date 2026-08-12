import math
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    region: str = "local"
    kms_key_arn: str | None = Field(default=None, max_length=2048)


class AgentOut(BaseModel):
    agent_id: UUID
    name: str
    pubkey: str
    region: str
    signing_algorithm: str = "ed25519"
    signer_key_id: str = "development"


class SourceIn(BaseModel):
    kind: str = Field(max_length=64)
    uri: str = Field(max_length=2048)
    trust_tier: str = Field(pattern="^(verified|partner|public|untrusted)$")
    region: str = "local"


class SourceOut(BaseModel):
    source_id: UUID
    kind: str
    uri: str
    trust_tier: str
    authority_rank: int = 0
    issuer: str = "legacy"


class BeliefIn(BaseModel):
    agent_id: UUID
    content: str = Field(min_length=1, max_length=8192)
    source_id: UUID | None = None
    parent_ids: list[UUID] = Field(default_factory=list, max_length=64)
    context_receipt_id: UUID | None = None
    embedding: list[float] | None = Field(default=None, min_length=1024, max_length=1024)

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and (
            any(not math.isfinite(component) for component in value)
            or not any(component != 0 for component in value)
        ):
            raise ValueError("embedding must contain finite values and cannot be all zero")
        return value


class BeliefOut(BaseModel):
    belief_id: UUID
    agent_id: UUID
    seq: int
    content: str
    status: str
    created_at: datetime
    hash: str
    prev_hash: str
    sig: str
    authority_rank: int = 0
    origin_source_ids: list[UUID] = Field(default_factory=list)
    context_receipt_id: UUID | None = None
    provenance_method: str = "legacy"
    provenance_version: str = "v1"
    attestation_version: str = "v1"


class ChainVerification(BaseModel):
    agent_id: UUID
    length: int
    valid: bool
    first_invalid_seq: int | None
    reason: str | None = None

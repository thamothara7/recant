from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    region: str = "local"


class AgentOut(BaseModel):
    agent_id: UUID
    name: str
    pubkey: str
    region: str


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


class BeliefIn(BaseModel):
    agent_id: UUID
    content: str = Field(min_length=1, max_length=8192)
    source_id: UUID | None = None
    parent_ids: list[UUID] = Field(default=[], max_length=64)
    embedding: list[float] | None = Field(default=None, min_length=1024, max_length=1024)


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


class ChainVerification(BaseModel):
    agent_id: UUID
    length: int
    valid: bool
    first_invalid_seq: int | None
    reason: str | None = None

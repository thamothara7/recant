"""Response models for the forensics API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BeliefSnapshot(BaseModel):
    """A belief as it appeared at a point in time."""

    belief_id: UUID
    agent_id: UUID
    seq: int
    content: str
    status: str
    created_at: datetime
    hash: str
    prev_hash: str
    sig: str
    source_id: UUID | None = None


class DerivationOut(BaseModel):
    child_id: UUID
    parent_id: UUID
    kind: str
    score: float | None = None


class CustodyStep(BaseModel):
    """One link in the custody chain."""

    belief: BeliefSnapshot
    parents: list[DerivationOut]
    children: list[DerivationOut]


class CustodyChainOut(BaseModel):
    agent_id: UUID
    agent_name: str
    chain_length: int
    steps: list[CustodyStep]
    valid: bool


class EventOut(BaseModel):
    event_id: UUID
    kind: str
    created_at: datetime
    payload: dict


class ActionOut(BaseModel):
    action_id: UUID
    belief_count: int
    actor: str
    sig: str
    newly_flipped_ids: list[UUID]
    created_at: datetime
    sig_valid: bool


class IncidentSummary(BaseModel):
    incident_id: UUID
    source_id: UUID
    source_uri: str
    source_kind: str
    source_trust_tier: str
    opened_by: str
    created_at: datetime
    closure_size: int
    agents_affected: list[dict]
    actions: list[ActionOut]
    events: list[EventOut]


class AffidavitOut(BaseModel):
    incident_id: UUID
    generated_by: str
    text: str


class ProvenanceOut(BaseModel):
    belief: BeliefSnapshot
    source: dict | None = None
    agent_name: str
    parents: list[DerivationOut]
    children: list[DerivationOut]
    chain_position: int
    chain_valid: bool
    sig_valid: bool


class BeliefsPage(BaseModel):
    agent_id: UUID
    agent_name: str
    as_of: str | None = None
    beliefs: list[BeliefSnapshot]
    count: int

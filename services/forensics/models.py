"""Response models for the forensics API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
    authority_rank: int = 0
    origin_source_ids: list[UUID] = Field(default_factory=list)
    context_receipt_id: UUID | None = None
    provenance_method: str = "legacy"
    provenance_version: str = "v1"
    attestation_version: str = "v1"


class DerivationOut(BaseModel):
    child_id: UUID
    parent_id: UUID
    kind: str
    score: float | None = None
    evidence_method: str = "declared"
    evidence_model: str | None = None
    evidence_version: str = "v1"


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
    signing_algorithm: str = "ed25519"
    signer_key_id: str = "legacy"
    attestation_version: str = "v1"


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


class ArchiveOut(BaseModel):
    """Receipt for one archived evidence bundle."""

    incident_id: UUID
    bucket: str
    keys: list[str]
    affidavit_generated_by: str


class BoardAgent(BaseModel):
    agent_id: UUID
    name: str
    region: str
    pubkey8: str
    signing_algorithm: str


class BoardSource(BaseModel):
    source_id: UUID
    kind: str
    uri: str
    trust_tier: str
    region: str
    authority_rank: int = 0
    issuer: str = "legacy"


class BoardOut(BaseModel):
    """The whole provenance graph in one read, for the console board.

    Read-only snapshot of the live seed: agents, sources, every belief with
    its current status, and the derivation edges (explicit and vector-inferred)
    that connect them. The console renders this exactly as it renders fixtures.
    """

    agents: list[BoardAgent]
    sources: list[BoardSource]
    beliefs: list[BeliefSnapshot]
    derivations: list[DerivationOut]


class CheckpointOut(BaseModel):
    checkpoint_id: UUID
    root_hash: str
    leaf_count: int
    previous_root_hash: str | None = None
    external_uri: str | None = None
    created_at: datetime
    sig: str
    signing_algorithm: str
    signer_key_id: str


class CheckpointVerificationOut(BaseModel):
    checkpoint_id: UUID
    signature_valid: bool
    merkle_root_valid: bool
    current_root_matches: bool
    external_copy_valid: bool | None = None

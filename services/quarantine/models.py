from uuid import UUID

from pydantic import BaseModel, Field


class InferredEdgeOut(BaseModel):
    child_id: UUID
    parent_id: UUID
    score: float


class RecantIn(BaseModel):
    source_id: UUID
    actor: str = Field(default="console", min_length=1, max_length=128)


class PreviewIn(BaseModel):
    source_id: UUID


class ClosureOut(BaseModel):
    source_id: UUID
    closure_ids: list[UUID]
    agent_ids: list[UUID]
    inferred_edges: list[InferredEdgeOut]
    rounds: int
    threshold: float
    rounds_capped: bool
    knn_truncated: bool


class PreviewOut(ClosureOut):
    would_flip: int


class RecantOut(ClosureOut):
    incident_id: UUID
    belief_count: int
    newly_flipped_ids: list[UUID]

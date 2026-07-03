// Domain types mirror the CockroachDB schema (db/migrations/0001_schema.sql) so
// this fixture layer can be swapped for the real forensics API without touching
// components. Status values match the belief_status enum exactly.

export type BeliefStatus = "active" | "suspect" | "quarantined" | "retracted";
export type TrustTier = "verified" | "partner" | "public" | "untrusted";
export type DerivationKind = "explicit" | "inferred";
export type AgentId = "researcher" | "support" | "ops";

export interface Agent {
  id: AgentId;
  name: string;
  role: string;
  region: string;
  pubkey8: string; // truncated hex, display only
}

export interface Source {
  id: string;
  kind: "web" | "doc" | "api";
  label: string;
  uri: string;
  trust: TrustTier;
}

export interface Belief {
  id: string;
  agentId: AgentId;
  seq: number;
  content: string;
  status: BeliefStatus;
  sourceId: string | null;
  hash: string; // full 64-hex; UI truncates to 8
  prevHash: string;
  sig: string;
  createdAt: string; // ISO UTC
  region: string;
}

export interface Derivation {
  childId: string;
  parentId: string;
  kind: DerivationKind;
  score: number; // 1.0 for explicit; cosine similarity for inferred
}

export interface Incident {
  id: string;
  sourceId: string;
  openedBy: string;
  summary: string;
}

// Judge Overlay chip: flashed when a backend response carries X-Recant-Primitive.
export type PrimitiveKind =
  | "SERIALIZABLE TXN"
  | "VECTOR kNN"
  | "CHANGEFEED"
  | "AOST"
  | "ROW TTL"
  | "MCP TOOL";

export interface JudgePrimitive {
  id: number;
  kind: PrimitiveKind;
  detail: string; // e.g. "3 nodes | 41ms"
  sql: string; // one-line SQL peek for the slide-out log
}

export interface ChangefeedEvent {
  id: number;
  at: string; // HH:MM:SS.mmm UTC
  text: string;
  tone: "neutral" | "quarantine" | "evict";
}

export interface ClusterNode {
  id: string;
  region: string;
  up: boolean;
}

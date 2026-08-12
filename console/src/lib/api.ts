// Thin client over the live Recant services. Every call maps the API response
// (snake_case, UUIDs, hex-string hashes) onto the console's domain types so
// components stay identical whether data is live or fixtures. Only used when
// CONFIG.live; the fixture path never imports this.

import { CONFIG } from "./config";
import type { ActionDecision, Agent, Belief, BeliefStatus, Derivation, Source, TrustTier } from "../data/types";

export interface Board {
  agents: Agent[];
  sources: Source[];
  beliefs: Belief[];
  derivations: Derivation[];
}

const FETCH_TIMEOUT_MS = 8000;

function requestHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    ...extra,
    ...(CONFIG.token ? { Authorization: `Bearer ${CONFIG.token}` } : {}),
  };
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<{ body: T; response: Response }> {
  // A reachable but unresponsive host must not pin loading or destructive
  // actions forever. Keep one timeout policy across reads and writes.
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, { ...init, signal: ctrl.signal });
    if (!response.ok) {
      throw new Error(`${init?.method ?? "GET"} ${url} -> ${response.status}`);
    }
    return { body: (await response.json()) as T, response };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`Request timed out after ${FETCH_TIMEOUT_MS / 1000} seconds`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

// The backend enum may gain values the UI does not know; clamp to the nearest
// safe display value rather than letting an undefined STATUS_META/TRUST_META
// lookup throw during render and blank the board.
const KNOWN_STATUS: BeliefStatus[] = ["active", "suspect", "quarantined", "retracted"];
const KNOWN_TRUST: TrustTier[] = ["verified", "partner", "public", "untrusted"];
const safeStatus = (s: string): BeliefStatus =>
  (KNOWN_STATUS as string[]).includes(s) ? (s as BeliefStatus) : "suspect";
const safeTrust = (t: string): TrustTier =>
  (KNOWN_TRUST as string[]).includes(t) ? (t as TrustTier) : "untrusted";

// The DB has no display "role" for an agent or "label" for a source; derive a
// readable fallback so the live board reads as well as the fixtures.
function hostOf(uri: string): string {
  try {
    return new URL(uri.includes("://") ? uri : `https://${uri}`).host || uri;
  } catch {
    return uri;
  }
}

const KIND_TO_UI: Record<string, Source["kind"]> = {
  web: "web",
  web_scrape: "web",
  doc: "doc",
  api: "api",
  feed: "api",
};

interface ApiBoard {
  agents: { agent_id: string; name: string; region: string; pubkey8: string; signing_algorithm: string }[];
  sources: {
    source_id: string;
    kind: string;
    uri: string;
    trust_tier: string;
    region: string;
    authority_rank: number;
    issuer: string;
  }[];
  beliefs: ApiBelief[];
  derivations: {
    child_id: string;
    parent_id: string;
    kind: string;
    score: number | null;
    evidence_method: string;
  }[];
}

interface ApiBelief {
  belief_id: string;
  agent_id: string;
  seq: number;
  content: string;
  status: string;
  created_at: string;
  hash: string;
  prev_hash: string;
  sig: string;
  source_id: string | null;
  authority_rank?: number;
  origin_source_ids?: string[];
}

function mapBelief(b: ApiBelief, region: string): Belief {
  return {
    id: b.belief_id,
    agentId: b.agent_id as Belief["agentId"],
    seq: b.seq,
    content: b.content,
    status: safeStatus(b.status),
    sourceId: b.source_id,
    hash: b.hash,
    prevHash: b.prev_hash,
    sig: b.sig.slice(0, 8) + "…",
    createdAt: b.created_at,
    region,
    authorityRank: b.authority_rank,
    originSourceIds: b.origin_source_ids,
  };
}

export async function fetchBoard(): Promise<Board> {
  const { body: raw } = await fetchJson<ApiBoard>(`${CONFIG.forensicsUrl}/board`, {
    headers: requestHeaders({ Accept: "application/json" }),
  });
  const agentRegion = new Map(raw.agents.map((a) => [a.agent_id, a.region]));
  return {
    agents: raw.agents.map((a) => ({
      id: a.agent_id as Agent["id"],
      name: a.name,
      role: "",
      region: a.region,
      pubkey8: a.pubkey8,
      signingAlgorithm: a.signing_algorithm,
    })),
    sources: raw.sources.map((s) => ({
      id: s.source_id,
      kind: KIND_TO_UI[s.kind] ?? "web",
      label: hostOf(s.uri),
      uri: s.uri,
      trust: safeTrust(s.trust_tier),
      authorityRank: s.authority_rank,
      issuer: s.issuer,
    })),
    beliefs: raw.beliefs.map((b) => mapBelief(b, agentRegion.get(b.agent_id) ?? "local")),
    derivations: raw.derivations.map((d) => ({
      childId: d.child_id,
      parentId: d.parent_id,
      kind: d.kind as Derivation["kind"],
      score: d.score ?? 1.0,
      evidenceMethod: d.evidence_method,
    })),
  };
}

export interface PreviewResult {
  closureIds: string[]; // full closure incl. vector-inferred (server-computed)
  agentCount: number;
  wouldFlip: number;
}

// Read-only taint preview: the real closure the recant would flip, including
// the vector-inferred copies the client cannot see until they are materialized.
export async function fetchPreview(sourceId: string): Promise<PreviewResult> {
  const { body } = await fetchJson<{
    closure_ids?: string[];
    agent_ids?: string[];
    would_flip?: number;
  }>(`${CONFIG.quarantineUrl}/taint/preview`, {
    method: "POST",
    headers: requestHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ source_id: sourceId }),
  });
  return {
    closureIds: body.closure_ids ?? [],
    agentCount: (body.agent_ids ?? []).length,
    wouldFlip: body.would_flip ?? 0,
  };
}

export interface RecantResult {
  incidentId: string;
  closureSize: number; // full contamination closure (closure_ids)
  newlyFlipped: string[]; // belief ids flipped active/suspect -> quarantined
  agentCount: number;
  inferredEdges: number;
  primitive: string | null;
}

// Returns the recant receipt plus the X-Recant-Primitive header, so the Judge
// Overlay flashes the real transaction timing instead of a scripted number.
export async function postRecant(sourceId: string, actor = "operator"): Promise<RecantResult> {
  const { body, response } = await fetchJson<{
    incident_id: string;
    closure_ids?: string[];
    newly_flipped_ids?: string[];
    agent_ids?: string[];
    inferred_edges?: unknown[];
  }>(`${CONFIG.quarantineUrl}/recant`, {
    method: "POST",
    headers: requestHeaders({
      "Content-Type": "application/json",
      "Idempotency-Key": `console-${crypto.randomUUID()}`,
    }),
    body: JSON.stringify({ source_id: sourceId, actor }),
  });
  return {
    incidentId: body.incident_id,
    closureSize: (body.closure_ids ?? []).length,
    newlyFlipped: body.newly_flipped_ids ?? [],
    agentCount: (body.agent_ids ?? []).length,
    inferredEdges: (body.inferred_edges ?? []).length,
    primitive: response.headers.get("X-Recant-Primitive"),
  };
}

interface ApiDecision {
  decision_id: string;
  agent_id: string;
  tool_name: string;
  support_belief_ids: string[];
  risk_class: string;
  required_authority: number;
  required_authority_label: string;
  observed_authority: number;
  observed_authority_label: string;
  decision: ActionDecision["decision"];
  reason: string;
  policy_version: string;
  created_at: string;
  sig: string;
}

export async function fetchActionDecisions(): Promise<ActionDecision[]> {
  if (!CONFIG.guardUrl) return [];
  const { body } = await fetchJson<ApiDecision[]>(`${CONFIG.guardUrl}/actions/decisions`, {
    headers: requestHeaders({ Accept: "application/json" }),
  });
  return body.map((decision) => ({
    id: decision.decision_id,
    agentId: decision.agent_id,
    toolName: decision.tool_name,
    supportBeliefIds: decision.support_belief_ids,
    riskClass: decision.risk_class,
    requiredAuthority: decision.required_authority,
    requiredAuthorityLabel: decision.required_authority_label.replaceAll("_", " "),
    observedAuthority: decision.observed_authority,
    observedAuthorityLabel: decision.observed_authority_label.replaceAll("_", " "),
    decision: decision.decision,
    reason: decision.reason,
    policyVersion: decision.policy_version,
    createdAt: decision.created_at,
    signature: decision.sig,
  }));
}

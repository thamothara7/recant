import type {
  Agent,
  Belief,
  ChangefeedEvent,
  ClusterNode,
  Derivation,
  Incident,
  Source,
} from "./types";

// Deterministic seed. Extends ops/seed/seed.py into the full contamination story
// the demo tells: a poisoned forum source, its vector-inferred paraphrase with no
// explicit provenance edge, and an in-flight bad action derived from that paraphrase.
// Fixed hashes/timestamps keep the board reproducible frame-for-frame (skill 4).
// All display strings are plain English (beginner-first redesign): "bot", not
// "agent"; sources carry human labels; jargon lives behind the Advanced toggle.

export const AGENTS: Agent[] = [
  { id: "researcher", name: "Research bot", role: "Reads websites and saves notes", region: "us-east", pubkey8: "a19f3c7d" },
  { id: "support", name: "Support bot", role: "Answers customer questions", region: "us-east", pubkey8: "6b02e4aa" },
  { id: "ops", name: "Ops bot", role: "Sends refund payments", region: "us-west", pubkey8: "d4f1902c" },
];

export const SOURCES: Source[] = [
  { id: "src_vendor", kind: "web", label: "Official refund policy", uri: "vendor.example.com/refund-policy", trust: "verified" },
  { id: "src_handbook", kind: "doc", label: "Company support handbook", uri: "s3://recant-evidence/handbook.pdf", trust: "partner" },
  { id: "src_status", kind: "api", label: "Partner status feed", uri: "partner.example.com/status", trust: "public" },
  { id: "src_forum", kind: "web", label: "Random forum post", uri: "forum.example.com/thread/42", trust: "untrusted" },
];

const T = (s: string) => `2026-07-02T14:${s}Z`;
const H = (p: string) => p + "e7a1c4b90d2f83a6155c0e9b4477af21d6c8b3e05f9a2d71c4b8e6f309a1d2c5b".slice(p.length);

// prev/sig are display-only textures here; the real chain lives in beliefs.hash/sig.
const B = (
  id: string,
  agentId: Belief["agentId"],
  seq: number,
  content: string,
  status: Belief["status"],
  sourceId: string | null,
  hp: string,
  t: string,
  region: string,
): Belief => ({
  id,
  agentId,
  seq,
  content,
  status,
  sourceId,
  hash: H(hp),
  prevHash: H(hp === "00000000" ? "00000000" : "9c1"),
  sig: (hp + "3f0a").slice(0, 8) + "…",
  createdAt: T(t),
  region,
});

export const BELIEFS: Belief[] = [
  // researcher
  B("bel_policy_window", "researcher", 1, "The standard refund window is 30 days.", "active", "src_vendor", "1a2b3c4d", "30:12.114", "us-east"),
  B("bel_policy_amount", "researcher", 2, "Refunds over 500 USD require manager approval.", "active", "src_vendor", "22cd91f0", "30:44.902", "us-east"),
  B("bel_forum_claim", "researcher", 3, "The refund window is 365 days.", "suspect", "src_forum", "e5484d10", "31:20.551", "us-east"),
  // support
  B("bel_handbook_flow", "support", 1, "Customers request refunds through the support portal.", "active", "src_handbook", "3fb27f08", "32:05.330", "us-east"),
  B("bel_support_window", "support", 2, "Support honors refunds inside the 30-day window.", "active", null, "7c44ab19", "32:41.087", "us-east"),
  B("bel_support_paraphrase", "support", 3, "We can extend refunds up to a year for loyal customers.", "suspect", null, "b8f10a2e", "33:58.640", "us-east"),
  // ops
  B("bel_ops_status", "ops", 1, "Partner refund processing API is operational.", "active", "src_status", "0c9d7e51", "34:12.900", "us-west"),
  B("bel_ops_plan", "ops", 2, "Scheduled refund batch runs nightly at 02:00 UTC.", "active", null, "4419aa2d", "34:50.233", "us-west"),
  B("bel_ops_action", "ops", 3, "Auto-approve pending 365-day refund for customer #4471.", "suspect", null, "e5c33017", "35:31.418", "us-west"),
];

export const DERIVATIONS: Derivation[] = [
  { childId: "bel_support_window", parentId: "bel_policy_window", kind: "explicit", score: 1.0 },
  { childId: "bel_ops_plan", parentId: "bel_ops_status", kind: "explicit", score: 1.0 },
  // the contamination: no foreign key, only vector proximity
  { childId: "bel_support_paraphrase", parentId: "bel_forum_claim", kind: "inferred", score: 0.91 },
  { childId: "bel_ops_action", parentId: "bel_support_paraphrase", kind: "inferred", score: 0.88 },
];

export const INCIDENT: Incident = {
  id: "inc_0042",
  sourceId: "src_forum",
  openedBy: "investigator",
  summary:
    "A random forum post claims refunds last 365 days. The official policy says 30 days. Every memory that grew from that post is a risk.",
};

export const CLUSTER: ClusterNode[] = [
  { id: "n1", region: "us-east-1a", up: true },
  { id: "n2", region: "us-east-1b", up: true },
  { id: "n3", region: "us-west-2a", up: true },
];

// Pre-scripted ticker history (newest appended at recant time by the store).
export const TICKER_SEED: ChangefeedEvent[] = [
  { id: 1, at: "14:35:31", text: "Ops bot saved memory #3 · signature checked", tone: "neutral" },
  { id: 2, at: "14:34:12", text: "Ops bot saved memory #1 · from Partner status feed", tone: "neutral" },
  { id: 3, at: "14:33:58", text: "Support bot memory #3 flagged: 91% meaning-match to forum post", tone: "neutral" },
];

// The taint closure of a source: its direct beliefs, then every belief reachable
// through derivation edges (explicit or inferred). Mirrors the Week 2 taint engine.
export function taintClosure(sourceId: string): string[] {
  const direct = BELIEFS.filter((b) => b.sourceId === sourceId).map((b) => b.id);
  const seen = new Set(direct);
  const queue = [...direct];
  while (queue.length) {
    const parent = queue.shift()!;
    for (const d of DERIVATIONS) {
      if (d.parentId === parent && !seen.has(d.childId)) {
        seen.add(d.childId);
        queue.push(d.childId);
      }
    }
  }
  return [...seen];
}

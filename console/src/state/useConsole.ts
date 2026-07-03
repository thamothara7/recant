import { create } from "zustand";
import {
  BELIEFS,
  CLUSTER,
  DERIVATIONS,
  TICKER_SEED,
  taintClosure,
} from "../data/fixtures";
import type {
  BeliefStatus,
  ChangefeedEvent,
  ClusterNode,
  JudgePrimitive,
  PrimitiveKind,
} from "../data/types";
import { clockUtc } from "../lib/format";

function initialStatuses(): Record<string, BeliefStatus> {
  return Object.fromEntries(BELIEFS.map((b) => [b.id, b.status]));
}

let chipId = 1;
let evtId = TICKER_SEED.length + 1;
const nowClock = () => clockUtc(new Date().toISOString());

interface ConsoleState {
  statuses: Record<string, BeliefStatus>;
  selectedBelief: string | null;
  hoverBelief: string | null;
  selectedSource: string | null;
  recanting: boolean;
  recantedSource: string | null;
  incidentOpen: boolean;
  aostHours: number; // 0 = live; negative = time-travel back
  overlayOn: boolean;
  recordingMode: boolean;
  primitives: JudgePrimitive[];
  primitiveLog: JudgePrimitive[];
  ticker: ChangefeedEvent[];
  cluster: ClusterNode[];

  selectBelief: (id: string | null) => void;
  hover: (id: string | null) => void;
  selectSource: (id: string | null) => void;
  recant: (sourceId: string) => void;
  setAost: (hours: number) => void;
  toggleOverlay: () => void;
  toggleRecording: () => void;
  killNode: (id: string) => void;
  reviveNode: (id: string) => void;
  flash: (kind: PrimitiveKind, detail: string, sql: string) => void;
  runMoment: (n: number) => void;
  reset: () => void;
}

export const useConsole = create<ConsoleState>((set, get) => ({
  statuses: initialStatuses(),
  selectedBelief: "bel_forum_claim",
  hoverBelief: null,
  selectedSource: null,
  recanting: false,
  recantedSource: null,
  incidentOpen: false,
  aostHours: 0,
  overlayOn: true,
  recordingMode: false,
  primitives: [],
  primitiveLog: [],
  ticker: TICKER_SEED,
  cluster: CLUSTER,

  selectBelief: (id) => set({ selectedBelief: id, selectedSource: null }),
  hover: (id) => set({ hoverBelief: id }),
  selectSource: (id) => set({ selectedSource: id, selectedBelief: null }),

  flash: (kind, detail, sql) => {
    const chip: JudgePrimitive = { id: chipId++, kind, detail, sql };
    set((s) => ({
      primitives: [...s.primitives, chip].slice(-3),
      primitiveLog: [chip, ...s.primitiveLog].slice(0, 30),
    }));
    window.setTimeout(() => {
      set((s) => ({ primitives: s.primitives.filter((c) => c.id !== chip.id) }));
    }, 4000);
  },

  recant: (sourceId) => {
    if (get().recanting || get().recantedSource === sourceId) return;
    const closure = taintClosure(sourceId);
    const explicit = closure.filter((id) =>
      DERIVATIONS.some((d) => d.childId === id && d.kind === "explicit"),
    ).length;
    const inferred = closure.length - explicit - 1;

    set({ recanting: true, incidentOpen: true, selectedSource: sourceId });
    get().flash("VECTOR kNN", `${Math.max(inferred, 0)} inferred · 23ms`, "SELECT belief_id FROM beliefs ORDER BY embedding <-> $1 LIMIT 12");

    // The recant sequence (skill 6): threads pulse, UV sweep, then statuses flip
    // in one visual beat. Kept under the 2.5s budget.
    window.setTimeout(() => {
      get().flash("SERIALIZABLE TXN", `${get().cluster.filter((n) => n.up).length} nodes · 41ms`, `UPDATE beliefs SET status='quarantined' WHERE belief_id = ANY($1) -- ${closure.length} rows`);
      set((s) => {
        const statuses = { ...s.statuses };
        for (const id of closure) statuses[id] = "quarantined";
        const agents = new Set(
          BELIEFS.filter((b) => closure.includes(b.id)).map((b) => b.agentId),
        );
        const events: ChangefeedEvent[] = [
          { id: evtId++, at: nowClock(), text: `recant(${sourceId}) · ${closure.length} beliefs quarantined across ${agents.size} agents`, tone: "quarantine" },
          { id: evtId++, at: nowClock(), text: "ops.action#3 aborted mid-flight · eviction notice delivered", tone: "evict" },
        ];
        return { statuses, ticker: [...events, ...s.ticker].slice(0, 40), recanting: false, recantedSource: sourceId };
      });
      get().flash("CHANGEFEED", "→ lambda · 380ms", "CREATE CHANGEFEED FOR beliefs INTO 'webhook-https://…'");
    }, 1150);
  },

  setAost: (hours) => {
    set({ aostHours: hours });
    if (hours < 0) get().flash("AOST", `@ ${hours}h`, `SELECT * FROM beliefs AS OF SYSTEM TIME '${hours}h' WHERE agent_id = $1`);
  },

  toggleOverlay: () => set((s) => ({ overlayOn: !s.overlayOn })),
  toggleRecording: () => set((s) => ({ recordingMode: !s.recordingMode })),

  killNode: (id) => {
    set((s) => ({ cluster: s.cluster.map((n) => (n.id === id ? { ...n, up: false } : n)) }));
    get().flash("MCP TOOL", "read-only · 8ms", "SHOW RANGES FROM TABLE beliefs -- forensics survives node loss");
  },
  reviveNode: (id) =>
    set((s) => ({ cluster: s.cluster.map((n) => (n.id === id ? { ...n, up: true } : n)) })),

  // The six proof moments (skill 5, Demo Director). Deterministic, no live typing.
  runMoment: (n) => {
    const s = get();
    switch (n) {
      case 1: // attested write
        s.selectBelief("bel_policy_window");
        s.flash("SERIALIZABLE TXN", "3 nodes · 39ms", "INSERT INTO beliefs (... , sig, prev_hash, hash) VALUES (...)");
        break;
      case 2: // semantic derivation, no explicit link
        s.selectBelief("bel_support_paraphrase");
        s.flash("VECTOR kNN", "12 matches · 23ms", "SELECT belief_id FROM beliefs ORDER BY embedding <-> $1 LIMIT 12");
        break;
      case 3: // recant
        s.recant("src_forum");
        break;
      case 4: // changefeed eviction / aborted action
        s.selectBelief("bel_ops_action");
        s.flash("CHANGEFEED", "→ lambda · 380ms", "CREATE CHANGEFEED FOR beliefs INTO 'webhook-https://…'");
        break;
      case 5: // AOST replay
        s.setAost(-2);
        break;
      case 6: // node kill
        if (s.cluster.some((node) => node.up && node.id === "n3")) s.killNode("n3");
        else s.reviveNode("n3");
        break;
      default:
        break;
    }
  },

  reset: () =>
    set({
      statuses: initialStatuses(),
      selectedBelief: "bel_forum_claim",
      selectedSource: null,
      recanting: false,
      recantedSource: null,
      incidentOpen: false,
      aostHours: 0,
      ticker: TICKER_SEED,
      cluster: CLUSTER,
      primitives: [],
    }),
}));

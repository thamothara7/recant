import { create } from "zustand";
import {
  BELIEFS,
  CLUSTER,
  DERIVATIONS,
  TICKER_SEED,
  taintClosure,
} from "../data/fixtures";
import { POISONED_SOURCE, STORY } from "../data/story";
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

// The statuses after the bad fact has been taken back — used by story steps that
// start in the "already recanted" world so Back/Next is fully deterministic.
function recantedStatuses(): Record<string, BeliefStatus> {
  const statuses = initialStatuses();
  for (const id of taintClosure(POISONED_SOURCE)) statuses[id] = "quarantined";
  return statuses;
}

// What the board looked like before any recant — the "past" the rewind shows.
const SEED_STATUSES = initialStatuses();

// Statuses as they should be DISPLAYED: rewinding shows the pre-recant world,
// so time travel visibly proves "blocked now, only flagged back then".
export const useDisplayStatuses = () =>
  useConsole((s) => (s.aostHours < 0 ? SEED_STATUSES : s.statuses));

let chipId = 1;
let evtId = TICKER_SEED.length + 1;
const nowClock = () => clockUtc(new Date().toISOString());

function recantEvents(sourceId: string): ChangefeedEvent[] {
  const closure = taintClosure(sourceId);
  const bots = new Set(BELIEFS.filter((b) => closure.includes(b.id)).map((b) => b.agentId));
  return [
    { id: evtId++, at: nowClock(), text: `Took back ${closure.length} memories from ${bots.size} bots — all at once`, tone: "quarantine" },
    { id: evtId++, at: nowClock(), text: "Ops bot's refund #4471 stopped just in time", tone: "evict" },
  ];
}

type Mode = "story" | "explore";

interface ConsoleState {
  mode: Mode;
  storyStep: number;
  advanced: boolean;

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

  setMode: (mode: Mode) => void;
  setStoryStep: (n: number) => void;
  nextStep: () => void;
  prevStep: () => void;
  toggleAdvanced: () => void;

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
  mode: "story",
  storyStep: 0,
  advanced: false,

  statuses: initialStatuses(),
  selectedBelief: null,
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

  setMode: (mode) => {
    if (mode === "story") {
      set({ mode });
      get().setStoryStep(get().storyStep);
    } else {
      // Leave the world as the story left it, but return the clock to "now".
      set({ mode, aostHours: 0 });
    }
  },

  // Each story step is applied as a full snapshot: Back always shows the exact
  // same picture as the first visit, no matter what was clicked in between.
  setStoryStep: (n) => {
    const step = STORY[Math.max(0, Math.min(n, STORY.length - 1))];
    const recanted = !!step.recanted;
    set({
      storyStep: Math.max(0, Math.min(n, STORY.length - 1)),
      statuses: recanted ? recantedStatuses() : initialStatuses(),
      recantedSource: recanted ? POISONED_SOURCE : null,
      ticker: recanted ? [...recantEvents(POISONED_SOURCE), ...TICKER_SEED] : TICKER_SEED,
      selectedBelief: step.select ?? null,
      selectedSource: null,
      aostHours: step.aost ?? 0,
      recanting: false,
      incidentOpen: false,
    });
  },
  nextStep: () => get().setStoryStep(get().storyStep + 1),
  prevStep: () => get().setStoryStep(get().storyStep - 1),
  toggleAdvanced: () => set((s) => ({ advanced: !s.advanced })),

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

    set({ recanting: true, incidentOpen: true });
    get().flash("VECTOR kNN", `${Math.max(inferred, 0)} inferred · 23ms`, "SELECT belief_id FROM beliefs ORDER BY embedding <-> $1 LIMIT 12");

    // The recant sequence (skill 6): threads pulse, UV sweep, then statuses flip
    // in one visual beat. Kept under the 2.5s budget.
    window.setTimeout(() => {
      get().flash("SERIALIZABLE TXN", `${get().cluster.filter((n) => n.up).length} nodes · 41ms`, `UPDATE beliefs SET status='quarantined' WHERE belief_id = ANY($1) -- ${closure.length} rows`);
      set((s) => {
        const statuses = { ...s.statuses };
        for (const id of closure) statuses[id] = "quarantined";
        return {
          statuses,
          ticker: [...recantEvents(sourceId), ...s.ticker].slice(0, 40),
          recanting: false,
          recantedSource: sourceId,
        };
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
      selectedBelief: null,
      selectedSource: null,
      recanting: false,
      recantedSource: null,
      incidentOpen: false,
      aostHours: 0,
      ticker: TICKER_SEED,
      cluster: CLUSTER,
      primitives: [],
      storyStep: 0,
    }),
}));

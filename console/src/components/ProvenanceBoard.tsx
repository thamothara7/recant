import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
} from "@xyflow/react";
import { BeliefCard } from "./BeliefCard";
import { custodyEdgeIds, layout } from "../lib/graph";
import { BELIEFS } from "../data/fixtures";
import { STATUS_META } from "../lib/format";
import type { BeliefStatus } from "../data/types";
import { useConsole, useDisplayStatuses } from "../state/useConsole";

const nodeTypes = { belief: BeliefCard };

function BoardInner() {
  const base = useMemo(() => layout(), []);
  const selected = useConsole((s) => s.selectedBelief);
  const hovered = useConsole((s) => s.hoverBelief);
  const recanting = useConsole((s) => s.recanting);

  // The custody thread lights along the selected (or hovered) belief's chain.
  const edges: Edge[] = useMemo(() => {
    const lit = custodyEdgeIds(selected ?? hovered);
    return base.edges.map((e) => {
      if (!lit.has(e.id)) return e;
      const base2 = e.className?.includes("inferred") ? "rf-edge-inferred" : "rf-edge-explicit";
      return { ...e, className: `${base2} rf-edge-active`, animated: true };
    });
  }, [base.edges, selected, hovered]);

  return (
    <ReactFlow
      nodes={base.nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.18 }}
      minZoom={0.5}
      maxZoom={1.4}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      panOnScroll
      zoomOnScroll={false}
      zoomOnDoubleClick={false}
      proOptions={{ hideAttribution: true }}
      onPaneClick={() => useConsole.getState().selectBelief(null)}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#2A3442" />
      {recanting && (
        <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
          <div
            className="absolute inset-x-0 h-24"
            style={{
              background:
                "linear-gradient(180deg, transparent, var(--uv-glow) 45%, rgba(139,126,248,.55) 50%, var(--uv-glow) 55%, transparent)",
              animation: "sweep 1.15s cubic-bezier(.4,0,.2,1) forwards",
            }}
          />
        </div>
      )}
    </ReactFlow>
  );
}

export function ProvenanceBoard() {
  const statuses = useDisplayStatuses();
  const suspect = Object.values(statuses).filter((v) => v === "suspect").length;
  const quarantined = Object.values(statuses).filter((v) => v === "quarantined").length;

  return (
    <section className="relative flex min-h-0 flex-1 flex-col">
      <header className="flex items-center justify-between gap-4 overflow-hidden border-b border-hairline px-4 py-2">
        <div className="flex shrink-0 items-baseline gap-2.5">
          <h2 className="label !text-bond-dim">Memory board</h2>
          <span className="whitespace-nowrap font-ui text-[11px] text-bond-dim">
            {BELIEFS.length} memories
            {suspect > 0 && (
              <span style={{ color: "var(--suspect)" }}> · {suspect} look wrong</span>
            )}
            {quarantined > 0 && (
              <span style={{ color: "var(--quarantined)" }}> · {quarantined} blocked</span>
            )}
          </span>
        </div>
        <Legend />
      </header>

      <div className="relative min-h-0 flex-1 room">
        <ReactFlowProvider>
          <BoardInner />
        </ReactFlowProvider>
      </div>
    </section>
  );
}

const LEGEND_STATUSES: BeliefStatus[] = ["active", "suspect", "quarantined"];

function Legend() {
  return (
    <div className="flex shrink-0 items-center gap-2.5">
      {LEGEND_STATUSES.map((s) => {
        const m = STATUS_META[s];
        return (
          <span key={s} className="flex items-center gap-1" title={m.label}>
            <span aria-hidden style={{ color: m.token, fontSize: 11 }}>
              {m.glyph}
            </span>
            <span className="label !text-[9px]" style={{ color: m.token }}>
              {m.label}
            </span>
          </span>
        );
      })}
      <span className="mx-0.5 h-3 w-px bg-hairline" />
      <span className="flex items-center gap-1.5">
        <svg width="18" height="6" aria-hidden>
          <line x1="0" y1="3" x2="18" y2="3" stroke="var(--hairline-strong)" strokeWidth="1.5" />
        </svg>
        <span className="label !text-[9px]">copied directly</span>
      </span>
      <span className="flex items-center gap-1.5">
        <svg width="18" height="6" aria-hidden>
          <line x1="0" y1="3" x2="18" y2="3" stroke="var(--uv-dim)" strokeWidth="1.5" strokeDasharray="2 4" />
        </svg>
        <span className="label !text-[9px]">reworded copy</span>
      </span>
    </div>
  );
}

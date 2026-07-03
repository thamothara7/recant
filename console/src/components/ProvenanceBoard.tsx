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
import { useConsole } from "../state/useConsole";

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
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#233042" />
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
  const suspect = useConsole(
    (s) => Object.values(s.statuses).filter((v) => v === "suspect").length,
  );
  const quarantined = useConsole(
    (s) => Object.values(s.statuses).filter((v) => v === "quarantined").length,
  );

  return (
    <section className="relative flex min-h-0 flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-hairline px-4 py-2">
        <div className="flex items-baseline gap-3">
          <h2 className="label !text-bond-dim">Provenance Board</h2>
          <span className="mono text-[11px] text-bond-dim">
            {BELIEFS.length} beliefs
            {suspect > 0 && (
              <span style={{ color: "var(--suspect)" }}> · {suspect} suspect</span>
            )}
            {quarantined > 0 && (
              <span style={{ color: "var(--quarantined)" }}> · {quarantined} quarantined</span>
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

function Legend() {
  return (
    <div className="flex items-center gap-4">
      <span className="flex items-center gap-1.5">
        <svg width="22" height="6" aria-hidden>
          <line x1="0" y1="3" x2="22" y2="3" stroke="var(--hairline-strong)" strokeWidth="1.5" />
        </svg>
        <span className="label !text-[9px]">explicit</span>
      </span>
      <span className="flex items-center gap-1.5">
        <svg width="22" height="6" aria-hidden>
          <line x1="0" y1="3" x2="22" y2="3" stroke="var(--uv-dim)" strokeWidth="1.5" strokeDasharray="2 4" />
        </svg>
        <span className="label !text-[9px]">inferred (vector)</span>
      </span>
    </div>
  );
}

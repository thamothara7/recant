import { useEffect, useMemo, useRef } from "react";
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
} from "@xyflow/react";
import { BeliefCard } from "./BeliefCard";
import { custodyEdgeIds, layout } from "../lib/graph";
import { STATUS_META } from "../lib/format";
import { useActiveBoard, useConsole, useDisplayStatuses } from "../state/useConsole";
import { STORY } from "../data/story";
import { Chip, Icon } from "./m3";

const nodeTypes = { belief: BeliefCard };

// Refit the graph whenever the board's box changes (inspector opening, mode
// switch, window resize) so the side panel shrinks the canvas instead of
// guillotining cards at its edge.
function AutoFit({
  container,
  graphKey,
}: {
  container: React.RefObject<HTMLDivElement>;
  graphKey: string;
}) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    const el = container.current;
    if (!el) return;
    let raf = 0;
    const fit = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => fitView({ padding: 0.12, duration: 200 }));
    };
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    // Node sets change between walkthrough steps without resizing the board.
    // Refit here so a newly introduced memory never lands below the fold.
    fit();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [container, fitView, graphKey]);
  return null;
}

function BoardInner({
  container,
  board,
}: {
  container: React.RefObject<HTMLDivElement>;
  board: ReturnType<typeof useActiveBoard>;
}) {
  // Re-layout only when the graph shape changes (fixtures are stable; live
  // recant refetches the board and legitimately re-lays out).
  const base = useMemo(
    () => layout(board.beliefs, board.derivations),
    [board.beliefs, board.derivations],
  );
  const selected = useConsole((s) => s.selectedBelief);
  const hovered = useConsole((s) => s.hoverBelief);
  const recanting = useConsole((s) => s.recanting);
  const graphKey = `${board.beliefs.map((belief) => belief.id).join(",")}|${board.derivations
    .map((edge) => `${edge.parentId}>${edge.childId}`)
    .join(",")}`;

  // The custody thread lights along the selected (or hovered) belief's chain.
  const edges: Edge[] = useMemo(() => {
    const lit = custodyEdgeIds(selected ?? hovered, board.derivations);
    return base.edges.map((e) => {
      if (!lit.has(e.id)) return e;
      const base2 = e.className?.includes("inferred") ? "rf-edge-inferred" : "rf-edge-explicit";
      return { ...e, className: `${base2} rf-edge-active`, animated: true };
    });
  }, [base.edges, selected, hovered, board.derivations]);

  return (
    <ReactFlow
      nodes={base.nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.12 }}
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
      <AutoFit container={container} graphKey={graphKey} />
      <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="var(--md-outline-variant)" />
      {recanting && (
        <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
          <div
            className="absolute inset-x-0 h-24"
            style={{
              background:
                "linear-gradient(to bottom, transparent, color-mix(in srgb, var(--md-primary) 10%, transparent), transparent)",
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
  const activeBoard = useActiveBoard();
  const mode = useConsole((s) => s.mode);
  const storyStep = useConsole((s) => s.storyStep);
  const selectSource = useConsole((s) => s.selectSource);
  const storyVisible = mode === "story" ? STORY[storyStep].visible : undefined;
  const board = useMemo(
    () =>
      storyVisible
        ? {
            ...activeBoard,
            beliefs: activeBoard.beliefs.filter((belief) => storyVisible.includes(belief.id)),
            derivations: activeBoard.derivations.filter(
              (edge) => storyVisible.includes(edge.parentId) && storyVisible.includes(edge.childId),
            ),
          }
        : activeBoard,
    [activeBoard, storyVisible],
  );
  const suspect = board.beliefs.filter((belief) => statuses[belief.id] === "suspect").length;
  const quarantined = board.beliefs.filter((belief) => statuses[belief.id] === "quarantined").length;
  const boardRef = useRef<HTMLDivElement>(null);
  // The one-line hint replaces the old always-open empty details panel.
  const explore = mode === "explore";
  const hasSelection = useConsole((s) => !!(s.selectedBelief || s.selectedSource));
  const untrusted = board.sources.find((source) => source.trust === "untrusted");
  const closure = untrusted ? closureIds(board, untrusted.id) : [];
  const contained =
    closure.length > 0 &&
    closure.every((id) => {
      const status = statuses[id] ?? board.beliefs.find((belief) => belief.id === id)?.status;
      return status === "quarantined" || status === "retracted";
    });

  return (
    <section className="relative flex min-h-0 flex-1 flex-col bg-surface">
      {/* flex-wrap: when the inspector narrows the board, the legend drops to
          its own row instead of clipping mid-word */}
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-outline-variant px-4 py-2">
        <div className="flex shrink-0 items-center gap-3">
          <h2 className="text-title-sm font-medium text-on-surface-variant">Memory board</h2>
          <span className="whitespace-nowrap text-body-sm text-on-surface-variant">
            {board.beliefs.length} {mode === "story" ? "memories in this step" : "memories"}
          </span>
          {explore && !hasSelection && (
            untrusted ? (
              <button
                onClick={() => selectSource(untrusted.id)}
                className="state-layer inline-flex items-center gap-1.5 rounded-full bg-error-container px-3 py-1 text-label-md font-medium text-on-error-container"
              >
                <Icon name="gpp_bad" size={16} />
                {contained
                  ? "Incident contained. Inspect the proof."
                  : `Review ${closure.length} memories from the untrusted source`}
              </button>
            ) : (
              <span className="whitespace-nowrap text-body-sm text-on-surface-variant">
                Click a card for its full story
              </span>
            )
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {suspect > 0 && (
            <Chip
              icon={STATUS_META.suspect.icon}
              label={`${suspect} look wrong`}
              container={STATUS_META.suspect.container}
              onContainer={STATUS_META.suspect.onContainer}
            />
          )}
          {quarantined > 0 && (
            <Chip
              icon={STATUS_META.quarantined.icon}
              label={`${quarantined} blocked`}
              container={STATUS_META.quarantined.container}
              onContainer={STATUS_META.quarantined.onContainer}
            />
          )}
          {board.derivations.length > 0 && <Legend />}
        </div>
      </header>

      <div ref={boardRef} className="relative min-h-0 flex-1">
        <ReactFlowProvider>
          <BoardInner container={boardRef} board={board} />
        </ReactFlowProvider>
      </div>
    </section>
  );
}

function closureIds(board: ReturnType<typeof useActiveBoard>, sourceId: string): string[] {
  const direct = board.beliefs.filter((belief) => belief.sourceId === sourceId).map((belief) => belief.id);
  const seen = new Set(direct);
  const pending = [...direct];
  while (pending.length) {
    const parent = pending.pop()!;
    for (const edge of board.derivations) {
      if (edge.parentId === parent && !seen.has(edge.childId)) {
        seen.add(edge.childId);
        pending.push(edge.childId);
      }
    }
  }
  return [...seen];
}

// Only the edge kinds need a legend: every card already carries a labeled
// status chip, so a status legend would be a redundant accessory.
function Legend() {
  return (
    <div className="flex shrink-0 items-center gap-3">
      <span className="flex items-center gap-1.5">
        <svg width="18" height="6" aria-hidden>
          <line x1="0" y1="3" x2="18" y2="3" stroke="var(--md-outline)" strokeWidth="1.5" />
        </svg>
        <span className="text-label-sm font-medium text-on-surface-variant">copied directly</span>
      </span>
      <span className="flex items-center gap-1.5">
        <svg width="18" height="6" aria-hidden>
          <line
            x1="0"
            y1="3"
            x2="18"
            y2="3"
            stroke="var(--md-tertiary)"
            strokeWidth="1.5"
            strokeDasharray="4 6"
            strokeLinecap="round"
          />
        </svg>
        <span className="text-label-sm font-medium text-on-surface-variant">reworded copy</span>
      </span>
    </div>
  );
}

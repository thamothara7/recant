import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { NODE_W, type BeliefNodeData } from "../lib/graph";
import { STATUS_META, clockUtc, short } from "../lib/format";
import { useActiveBoard, useConsole, useDisplayStatuses } from "../state/useConsole";
import { Chip } from "./m3";

// One memory, rendered as an M3 outlined card a first-time viewer can read
// cold: who saved it, what it says, whether it's healthy, in plain words.
// Hashes and timestamps only appear with the Advanced toggle. Still a
// react-flow node so arrows attach.
export function BeliefCard({ id, data }: NodeProps<Node<BeliefNodeData>>) {
  const { belief } = data;
  const board = useActiveBoard();
  const agentName = (aid: string) => board.agents.find((a) => a.id === aid)?.name ?? aid;
  const status = useDisplayStatuses()[id] ?? belief.status;
  const selected = useConsole((s) => s.selectedBelief === id);
  const hovered = useConsole((s) => s.hoverBelief === id);
  const advanced = useConsole((s) => s.advanced);
  const select = useConsole((s) => s.selectBelief);
  const hover = useConsole((s) => s.hover);
  const meta = STATUS_META[status];
  const src = belief.sourceId ? board.sources.find((s) => s.id === belief.sourceId) : null;

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${agentName(belief.agentId)} memory ${belief.seq}, ${meta.label}: ${belief.content}`}
      onClick={() => select(id)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), select(id))}
      onMouseEnter={() => hover(id)}
      onMouseLeave={() => hover(null)}
      className={`relative flex select-none flex-col rounded-md3-md border bg-surface-container-lowest p-3 transition-[box-shadow,border-color] duration-150 ${
        selected
          ? "border-primary shadow-elevation-1 ring-1 ring-primary"
          : `border-outline-variant ${hovered ? "shadow-elevation-1" : ""}`
      }`}
      style={{ width: NODE_W }}
    >
      <Handle type="target" position={Position.Left} className="!h-1 !w-1 !min-w-0 !border-0 !bg-transparent" />
      <Handle type="source" position={Position.Right} className="!h-1 !w-1 !min-w-0 !border-0 !bg-transparent" />

      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate text-label-md font-medium text-on-surface-variant">
          {agentName(belief.agentId)}
        </span>
        <Chip
          icon={meta.icon}
          label={meta.label}
          container={meta.container}
          onContainer={meta.onContainer}
          className="shrink-0"
        />
      </div>

      <p
        className="mt-1 text-body-md text-on-surface"
        style={{
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {belief.content}
      </p>

      {/* The source line is the demo's whole argument (trusted vs forum post),
          so it always gets the full row; the advanced hash/clock stacks under
          it instead of truncating it away. */}
      <div className="mt-1">
        <span className="block truncate text-body-sm text-on-surface-variant">
          {src ? `from: ${src.label}` : "built from other memories"}
        </span>
        {advanced && (
          <span
            className="mono mt-0.5 flex items-center gap-2 text-label-md text-on-surface-variant"
            title={`hash ${short(belief.hash)}`}
          >
            <span>{short(belief.hash)}</span>
            <span>{clockUtc(belief.createdAt)}</span>
          </span>
        )}
      </div>
    </div>
  );
}

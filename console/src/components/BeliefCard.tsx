import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import type { BeliefNodeData } from "../lib/graph";
import { AGENTS, SOURCES } from "../data/fixtures";
import { STATUS_META, clockUtc, short } from "../lib/format";
import { useConsole } from "../state/useConsole";

const agentName = (id: string) => AGENTS.find((a) => a.id === id)?.name ?? id;

// A belief rendered as a tagged evidence item: crisp 2px corners, a perforated
// left stub carrying the status glyph, mono data textures. The whole node is a
// react-flow custom node so the custody thread (edges) attaches to it.
export function BeliefCard({ id, data }: NodeProps<Node<BeliefNodeData>>) {
  const { belief } = data;
  const status = useConsole((s) => s.statuses[id] ?? belief.status);
  const selected = useConsole((s) => s.selectedBelief === id);
  const hovered = useConsole((s) => s.hoverBelief === id);
  const recanting = useConsole((s) => s.recanting);
  const select = useConsole((s) => s.selectBelief);
  const hover = useConsole((s) => s.hover);
  const meta = STATUS_META[status];
  const src = belief.sourceId ? SOURCES.find((s) => s.id === belief.sourceId) : null;
  const active = selected || hovered;
  const quarantining = recanting && (status === "suspect" || status === "quarantined");

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${agentName(belief.agentId)} belief ${belief.seq}, ${meta.label}: ${belief.content}`}
      onClick={() => select(id)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), select(id))}
      onMouseEnter={() => hover(id)}
      onMouseLeave={() => hover(null)}
      className="group relative flex select-none rounded-tag transition-[box-shadow,transform,border-color] duration-150"
      style={{
        width: 244,
        background: "var(--panel)",
        border: `1px solid ${selected ? "var(--uv)" : "var(--hairline)"}`,
        boxShadow: selected
          ? "0 0 0 1px var(--uv), 0 0 22px -6px var(--uv-glow), var(--tw-shadow, 0 8px 24px -16px rgba(0,0,0,.7))"
          : hovered
            ? "0 8px 24px -16px rgba(0,0,0,.7)"
            : "none",
        transform: active ? "translateY(-1px)" : "none",
        opacity: quarantining ? 0.96 : 1,
      }}
    >
      <Handle type="target" position={Position.Left} className="!h-1 !w-1 !min-w-0 !border-0 !bg-transparent" />
      <Handle type="source" position={Position.Right} className="!h-1 !w-1 !min-w-0 !border-0 !bg-transparent" />

      {/* perforated status stub */}
      <div
        className="perf-left flex w-8 shrink-0 flex-col items-center justify-between rounded-l-tag py-2"
        style={{ background: `color-mix(in srgb, ${meta.token} 9%, transparent)` }}
      >
        <span aria-hidden className="text-[13px] leading-none" style={{ color: meta.token }}>
          {meta.glyph}
        </span>
        <span className="mono text-[8px] text-bond-dim rotate-180 [writing-mode:vertical-rl] tracking-wider">
          #{belief.seq}
        </span>
      </div>

      <div className="min-w-0 flex-1 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="mono text-[10px] uppercase tracking-[0.12em] text-bond-dim">
            {agentName(belief.agentId)}
          </span>
          <span className="mono text-[10px] text-bond/80" style={{ color: active ? "var(--uv)" : undefined }}>
            {short(belief.hash)}
          </span>
        </div>

        <p
          className="mt-1 font-ui text-[12.5px] leading-snug text-bond"
          style={{
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {belief.content}
        </p>

        <div className="mt-1.5 flex items-center justify-between">
          <span className="mono text-[9px] text-bond-dim">
            {src ? src.label : "derived"}
          </span>
          <span className="mono text-[9px] text-bond-dim/80">{clockUtc(belief.createdAt)}</span>
        </div>
      </div>
    </div>
  );
}

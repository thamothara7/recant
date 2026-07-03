import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import type { BeliefNodeData } from "../lib/graph";
import { AGENTS, SOURCES } from "../data/fixtures";
import { STATUS_META, clockUtc, short } from "../lib/format";
import { useConsole, useDisplayStatuses } from "../state/useConsole";

const agentName = (id: string) => AGENTS.find((a) => a.id === id)?.name ?? id;

// One memory, rendered as a card a first-time viewer can read cold: who saved it,
// what it says, whether it's healthy — in plain words. Hashes and timestamps only
// appear with the Advanced toggle. Still a react-flow node so arrows attach.
export function BeliefCard({ id, data }: NodeProps<Node<BeliefNodeData>>) {
  const { belief } = data;
  const status = useDisplayStatuses()[id] ?? belief.status;
  const selected = useConsole((s) => s.selectedBelief === id);
  const hovered = useConsole((s) => s.hoverBelief === id);
  const recanting = useConsole((s) => s.recanting);
  const advanced = useConsole((s) => s.advanced);
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
      aria-label={`${agentName(belief.agentId)} memory ${belief.seq}, ${meta.label}: ${belief.content}`}
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

      {/* status stub: glyph + evidence-tag perforation */}
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
          <span className="font-ui text-[10.5px] font-medium uppercase tracking-[0.1em] text-bond-dim">
            {agentName(belief.agentId)}
          </span>
          <span className="text-[10px] font-medium" style={{ color: meta.token }}>
            {meta.label}
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
          <span className="font-ui text-[9.5px] text-bond-dim">
            {src ? `from: ${src.label}` : "built from other memories"}
          </span>
          {advanced && (
            <span className="mono text-[9px] text-bond-dim/80" title={`hash ${short(belief.hash)}`}>
              {short(belief.hash)} · {clockUtc(belief.createdAt)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

import type { BeliefStatus } from "../data/types";
import { STATUS_META } from "../lib/format";

// Color + glyph + label, always together. Never color alone.
export function StatusBadge({
  status,
  size = "sm",
}: {
  status: BeliefStatus;
  size?: "sm" | "xs";
}) {
  const m = STATUS_META[status];
  const pad = size === "xs" ? "px-1.5 py-[1px] text-[10px]" : "px-2 py-[2px] text-[11px]";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-tag font-ui font-medium ${pad}`}
      style={{
        color: m.token,
        background: `color-mix(in srgb, ${m.token} 12%, transparent)`,
        border: `1px solid color-mix(in srgb, ${m.token} 40%, transparent)`,
      }}
    >
      <span aria-hidden style={{ lineHeight: 1 }}>
        {m.glyph}
      </span>
      <span className="uppercase tracking-[0.1em]">{m.label}</span>
    </span>
  );
}

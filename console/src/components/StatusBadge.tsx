import type { BeliefStatus } from "../data/types";
import { STATUS_META } from "../lib/format";
import { Chip } from "./m3";

// Icon + label + tonal container, always together. Never color alone.
// The M3 chip is one size; the size prop is kept for caller compatibility.
export function StatusBadge({
  status,
}: {
  status: BeliefStatus;
  size?: "sm" | "xs";
}) {
  const m = STATUS_META[status];
  return <Chip icon={m.icon} label={m.label} container={m.container} onContainer={m.onContainer} />;
}

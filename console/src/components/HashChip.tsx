import { useState } from "react";
import { copy, short } from "../lib/format";

// Mono hash truncated to 8 chars with a copy affordance (skill 2).
export function HashChip({
  hash,
  label,
  className = "",
}: {
  hash: string;
  label?: string;
  className?: string;
}) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async (e) => {
        e.stopPropagation();
        await copy(hash);
        setDone(true);
        window.setTimeout(() => setDone(false), 900);
      }}
      title={`Copy ${hash}`}
      className={`group inline-flex items-center gap-1 mono text-[11px] text-bond-dim hover:text-bond transition-colors ${className}`}
    >
      {label && <span className="text-bond-dim/70">{label}</span>}
      <span className="text-bond/85">{short(hash)}</span>
      <span
        aria-hidden
        className="text-[9px] text-bond-dim/60 group-hover:text-uv transition-colors"
      >
        {done ? "copied" : "copy"}
      </span>
    </button>
  );
}

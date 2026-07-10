import { useState } from "react";
import { copy, short } from "../lib/format";
import { Icon } from "./m3";

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
    <span
      className={`inline-flex h-6 items-center gap-1 rounded-md3-sm bg-surface-container-high px-2 text-on-surface-variant ${className}`}
    >
      {label && <span className="text-label-md">{label}</span>}
      <span className="mono text-label-md">{short(hash)}</span>
      <button
        type="button"
        aria-label="Copy hash"
        title={`Copy ${hash}`}
        onClick={async (e) => {
          e.stopPropagation();
          await copy(hash);
          setDone(true);
          window.setTimeout(() => setDone(false), 900);
        }}
        className="state-layer -mr-1.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
      >
        <Icon name={done ? "check" : "content_copy"} size={14} />
      </button>
    </span>
  );
}

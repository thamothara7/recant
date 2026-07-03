import { useConsole } from "../state/useConsole";

// The time rewind (AS OF SYSTEM TIME underneath). 0 = now; dragging back shows
// the board exactly as it was then. Plain words; the SQL lives in the Judge
// Overlay for Advanced viewers.
const MARKS = [-6, -5, -4, -3, -2, -1, 0];

export function AostScrubber() {
  const aost = useConsole((s) => s.aostHours);
  const setAost = useConsole((s) => s.setAost);
  const live = aost === 0;

  return (
    <div className="flex h-11 items-center gap-4 border-b border-hairline bg-[var(--ink-2)] px-4">
      <span className="label whitespace-nowrap">Rewind time</span>

      <div className="relative flex-1">
        <input
          type="range"
          min={-6}
          max={0}
          step={1}
          value={aost}
          onChange={(e) => setAost(Number(e.target.value))}
          aria-label="How many hours to rewind"
          className="aost-range w-full"
        />
        <div className="pointer-events-none mt-1 flex justify-between">
          {MARKS.map((m) => (
            <span key={m} className="font-ui text-[9px] text-bond-dim/70">
              {m === 0 ? "now" : `${-m}h ago`}
            </span>
          ))}
        </div>
      </div>

      <span
        className="inline-flex items-center gap-1.5 rounded-tag px-2 py-1 font-ui text-[11px] font-medium"
        style={{
          color: live ? "var(--attested)" : "var(--uv)",
          border: `1px solid color-mix(in srgb, ${live ? "var(--attested)" : "var(--uv)"} 40%, transparent)`,
          background: `color-mix(in srgb, ${live ? "var(--attested)" : "var(--uv)"} 10%, transparent)`,
        }}
      >
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: live ? "var(--attested)" : "var(--uv)" }}
        />
        {live ? "Now" : `Viewing ${-aost}h ago`}
      </span>

      <button
        disabled={live}
        className="rounded-tag border border-hairline px-2 py-1 font-ui text-[11px] text-bond-dim transition-colors hover:text-bond disabled:opacity-40"
        onClick={() => setAost(0)}
      >
        Back to now
      </button>
    </div>
  );
}

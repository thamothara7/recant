import { useConsole } from "../state/useConsole";

// Plain header: what the app is, Story/Explore switch, and one Advanced toggle
// that reveals the judge-facing demo machinery (moments 1-6, overlay, recording).
const MOMENTS = [
  { n: 1, label: "Write" },
  { n: 2, label: "Derive" },
  { n: 3, label: "Recant" },
  { n: 4, label: "Evict" },
  { n: 5, label: "Replay" },
  { n: 6, label: "Kill node" },
];

export function TopBar() {
  const mode = useConsole((s) => s.mode);
  const setMode = useConsole((s) => s.setMode);
  const advanced = useConsole((s) => s.advanced);
  const toggleAdvanced = useConsole((s) => s.toggleAdvanced);
  const overlayOn = useConsole((s) => s.overlayOn);
  const recordingMode = useConsole((s) => s.recordingMode);
  const toggleOverlay = useConsole((s) => s.toggleOverlay);
  const toggleRecording = useConsole((s) => s.toggleRecording);
  const runMoment = useConsole((s) => s.runMoment);
  const reset = useConsole((s) => s.reset);

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-hairline bg-[var(--ink-2)] px-4">
      <div className="flex items-center gap-3">
        <div
          className="flex h-6 w-6 items-center justify-center rounded-tag border"
          style={{ borderColor: "var(--uv)", boxShadow: "0 0 12px -3px var(--uv-glow)" }}
        >
          <span className="font-display text-[13px] leading-none" style={{ color: "var(--uv)" }}>
            R
          </span>
        </div>
        <div className="leading-none">
          <div className="font-display text-[15px] tracking-[0.02em] text-bond">Recant</div>
          <div className="font-ui text-[10px] text-bond-dim">Take back bad AI memories</div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* judge-facing demo machinery, only when Advanced is on */}
        {advanced && (
          <>
            <div className="hidden items-center gap-1 lg:flex">
              {MOMENTS.map((m) => (
                <button
                  key={m.n}
                  onClick={() => runMoment(m.n)}
                  className="group flex items-center gap-1 rounded-tag border border-hairline px-2 py-1 font-ui text-[11px] text-bond-dim transition-colors hover:border-uv hover:text-bond"
                >
                  <span className="mono text-[9px] text-bond-dim group-hover:text-uv">{m.n}</span>
                  {m.label}
                </button>
              ))}
              <button
                onClick={reset}
                className="rounded-tag border border-hairline px-2 py-1 font-ui text-[11px] text-bond-dim transition-colors hover:text-bond"
              >
                <span className="mono text-[9px]">R</span> reset
              </button>
            </div>
            <Toggle label="Judge J" on={overlayOn} onClick={toggleOverlay} />
            <Toggle label="Rec V" on={recordingMode} onClick={toggleRecording} tone="rec" />
            <span className="h-4 w-px bg-hairline" />
          </>
        )}

        {/* Story / Explore switch */}
        <div className="flex items-center rounded-panel border border-hairline p-0.5" role="tablist" aria-label="View mode">
          {(["story", "explore"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className="rounded-tag px-3 py-1 font-ui text-[12.5px] font-medium capitalize transition-colors"
              style={{
                background: mode === m ? "var(--uv)" : "transparent",
                color: mode === m ? "#0e0b1f" : "var(--bond-dim)",
              }}
            >
              {m === "story" ? "Story" : "Explore"}
            </button>
          ))}
        </div>

        <Toggle label="Advanced" on={advanced} onClick={toggleAdvanced} />
      </div>
    </header>
  );
}

function Toggle({
  label,
  on,
  onClick,
  tone = "uv",
}: {
  label: string;
  on: boolean;
  onClick: () => void;
  tone?: "uv" | "rec";
}) {
  const color = tone === "rec" ? "var(--quarantined)" : "var(--uv)";
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className="flex items-center gap-1.5 rounded-tag px-2 py-1 font-ui text-[11px] transition-colors"
      style={{
        color: on ? color : "var(--bond-dim)",
        border: `1px solid ${on ? `color-mix(in srgb, ${color} 45%, transparent)` : "var(--hairline)"}`,
        background: on ? `color-mix(in srgb, ${color} 10%, transparent)` : "transparent",
      }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: on ? color : "var(--hairline-strong)" }} />
      {label}
    </button>
  );
}

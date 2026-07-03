import { useConsole } from "../state/useConsole";

const TONE: Record<string, string> = {
  neutral: "var(--bond-dim)",
  quarantine: "var(--quarantined)",
  evict: "var(--attested)", // a stopped bad action is a good outcome; --uv stays reserved for interaction
};

// Live changefeed, newest first (skill 4) — labeled in plain words.
export function ChangefeedTicker() {
  const ticker = useConsole((s) => s.ticker);

  return (
    <div className="flex min-w-0 flex-1 items-center gap-3 border-r border-hairline px-4">
      <span className="label whitespace-nowrap">Live activity</span>
      <div className="flex min-w-0 flex-1 items-center gap-5 overflow-hidden">
        {ticker.slice(0, 4).map((e) => (
          <div
            key={e.id}
            className="flex shrink-0 items-center gap-2"
            style={{ animation: "ticker-in .2s ease-out" }}
          >
            <span className="mono text-[10px] text-bond-dim/70">{e.at}</span>
            <span
              className="h-1 w-1 rounded-full"
              style={{ background: TONE[e.tone] }}
            />
            <span className="font-ui text-[11px] truncate" style={{ color: e.tone === "neutral" ? "var(--bond)" : TONE[e.tone] }}>
              {e.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

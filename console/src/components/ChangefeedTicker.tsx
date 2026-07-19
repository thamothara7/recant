import { useConsole } from "../state/useConsole";
import { Icon } from "./m3";

// Tone accents are icon + color together; status is never color alone.
const TONE_ICON: Record<string, { icon: string; className: string }> = {
  neutral: { icon: "sync", className: "text-on-surface-variant" },
  quarantine: { icon: "block", className: "text-error" },
  evict: { icon: "bolt", className: "text-tertiary" },
};

// Live changefeed, newest first (skill 4), labeled in plain words.
export function ChangefeedTicker() {
  const ticker = useConsole((s) => s.ticker);

  if (ticker.length === 0) {
    return (
      <div className="flex min-w-0 flex-1 items-center gap-2 text-body-sm text-on-surface-variant">
        <Icon name="schedule" size={16} />
        <span>No eviction events observed in this browser session.</span>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-3">
      <span className="whitespace-nowrap text-label-md font-medium text-on-surface-variant">Live activity</span>
      {/* Right-edge fade instead of a mid-word clip: a paused video frame
          should read as an intentional fade, not a rendering bug. */}
      <div
        className="flex min-w-0 flex-1 items-center gap-5 overflow-hidden"
        style={{
          maskImage: "linear-gradient(to right, black 90%, transparent)",
          WebkitMaskImage: "linear-gradient(to right, black 90%, transparent)",
        }}
      >
        {ticker.slice(0, 4).map((e) => (
          <div
            key={e.id}
            className={`flex min-w-0 shrink-0 items-center gap-1.5 px-1 ${
              e.tone === "quarantine" || e.tone === "evict" ? "ticker-quarantine" : ""
            }`}
            style={{ animation: "ticker-in .2s ease-out" }}
          >
            <Icon
              name={(TONE_ICON[e.tone] ?? TONE_ICON.neutral).icon}
              size={14}
              className={(TONE_ICON[e.tone] ?? TONE_ICON.neutral).className}
            />
            <span className="mono text-label-sm text-on-surface-variant">{e.at}</span>
            <span className="text-outline">·</span>
            <span className="truncate text-body-sm text-on-surface">{e.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

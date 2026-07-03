import { TopBar } from "./TopBar";
import { AostScrubber } from "./AostScrubber";
import { LeftRail } from "./LeftRail";
import { ProvenanceBoard } from "./ProvenanceBoard";
import { Inspector } from "./Inspector";
import { ChangefeedTicker } from "./ChangefeedTicker";
import { ClusterBar } from "./ClusterBar";
import { JudgeOverlay } from "./JudgeOverlay";
import { useConsole } from "../state/useConsole";

// The forensic layout (skill 4): top strip, three columns, bottom strip. Desktop
// console at >=1280px; the board is always the hero.
// The demo's live edge is 14:35:31.418 UTC; past mode shows that minus the offset.
const LIVE_SECONDS = 14 * 3600 + 35 * 60 + 31;
function aostClock(hoursBack: number): string {
  const total = LIVE_SECONDS + hoursBack * 3600; // hoursBack is negative
  const p = (x: number, w = 2) => String(x).padStart(w, "0");
  return `${p(Math.floor(total / 3600))}:${p(Math.floor((total % 3600) / 60))}:${p(total % 60)}.418`;
}

export function AppShell() {
  const aostHours = useConsole((s) => s.aostHours);
  const pastMode = aostHours < 0;
  const recording = useConsole((s) => s.recordingMode);

  return (
    <div className={`grain relative flex h-full min-w-[1180px] flex-col ${recording ? "recording" : ""}`}>
      <TopBar />
      <AostScrubber />

      <div className="relative flex min-h-0 flex-1">
        <LeftRail />
        <main className="relative flex min-h-0 flex-1 flex-col">
          <ProvenanceBoard />
          {/* Past-mode UV wash over the board (skill 4) */}
          {pastMode && (
            <div
              className="pointer-events-none absolute inset-0 z-10"
              style={{ background: "color-mix(in srgb, var(--uv) 8%, transparent)", mixBlendMode: "screen" }}
            >
              <div className="absolute left-1/2 top-4 -translate-x-1/2 rounded-tag border border-[color-mix(in_srgb,var(--uv)_50%,transparent)] bg-[var(--ink-2)] px-3 py-1 mono text-[11px]" style={{ color: "var(--uv)" }}>
                VIEWING: {aostClock(aostHours)} UTC
              </div>
            </div>
          )}
        </main>
        <Inspector />
      </div>

      <div className="flex h-11 shrink-0 items-center border-t border-hairline bg-[var(--ink-2)]">
        <ChangefeedTicker />
        <ClusterBar />
      </div>

      <JudgeOverlay />
    </div>
  );
}

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
export function AppShell() {
  const pastMode = useConsole((s) => s.aostHours < 0);
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
                VIEWING: 12:32:07.114 UTC
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

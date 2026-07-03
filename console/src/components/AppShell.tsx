import { TopBar } from "./TopBar";
import { AostScrubber } from "./AostScrubber";
import { LeftRail } from "./LeftRail";
import { ProvenanceBoard } from "./ProvenanceBoard";
import { Inspector } from "./Inspector";
import { ChangefeedTicker } from "./ChangefeedTicker";
import { ClusterBar } from "./ClusterBar";
import { JudgeOverlay } from "./JudgeOverlay";
import { StoryPanel } from "./StoryPanel";
import { STORY } from "../data/story";
import { useConsole } from "../state/useConsole";

// Beginner-first layout. Story mode: board + walkthrough strip, nothing else.
// Explore mode: the full three-column console with plain-English labels.
// Judge Overlay, Recording Mode, and cluster controls only exist behind Advanced.
// The demo's live edge is 14:35:31.418 UTC; past mode shows that minus the offset.
const LIVE_SECONDS = 14 * 3600 + 35 * 60 + 31;
function aostClock(hoursBack: number): string {
  const total = LIVE_SECONDS + hoursBack * 3600; // hoursBack is negative
  const p = (x: number, w = 2) => String(x).padStart(w, "0");
  return `${p(Math.floor(total / 3600))}:${p(Math.floor((total % 3600) / 60))}:${p(total % 60)}`;
}

export function AppShell() {
  const mode = useConsole((s) => s.mode);
  const storyStep = useConsole((s) => s.storyStep);
  const advanced = useConsole((s) => s.advanced);
  const aostHours = useConsole((s) => s.aostHours);
  const pastMode = aostHours < 0;
  const recording = useConsole((s) => s.recordingMode);

  const story = mode === "story";
  // The rewind slider appears once the story introduces it, and always in Explore.
  const showScrubber = !story || !!STORY[storyStep].aost || storyStep >= 5;

  return (
    <div className={`grain relative flex h-full min-w-[1180px] flex-col ${recording && advanced ? "recording" : ""}`}>
      <TopBar />
      {showScrubber && <AostScrubber />}

      <div className="relative flex min-h-0 flex-1">
        {!story && <LeftRail />}
        <main className="relative flex min-h-0 flex-1 flex-col">
          <ProvenanceBoard />
          {/* Past-mode wash over the board */}
          {pastMode && (
            <div
              className="pointer-events-none absolute inset-0 z-10"
              style={{ background: "color-mix(in srgb, var(--uv) 8%, transparent)", mixBlendMode: "screen" }}
            >
              <div className="absolute left-1/2 top-4 -translate-x-1/2 rounded-tag border border-[color-mix(in_srgb,var(--uv)_50%,transparent)] bg-[var(--ink-2)] px-3 py-1 font-ui text-[12px]" style={{ color: "var(--uv)" }}>
                Viewing the past: {Math.abs(aostHours)}h ago <span className="mono text-[10px]">({aostClock(aostHours)} UTC)</span>
              </div>
            </div>
          )}
        </main>
        {!story && <Inspector />}
      </div>

      {story && <StoryPanel />}

      <div className="flex h-11 shrink-0 items-center border-t border-hairline bg-[var(--ink-2)]">
        <ChangefeedTicker />
        {advanced && <ClusterBar />}
      </div>

      {advanced && <JudgeOverlay />}
    </div>
  );
}

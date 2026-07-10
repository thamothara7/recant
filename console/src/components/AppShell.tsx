import { TopBar } from "./TopBar";
import { AostScrubber } from "./AostScrubber";
import { LeftRail } from "./LeftRail";
import { ProvenanceBoard } from "./ProvenanceBoard";
import { Inspector } from "./Inspector";
import { ChangefeedTicker } from "./ChangefeedTicker";
import { ClusterBar } from "./ClusterBar";
import { JudgeOverlay } from "./JudgeOverlay";
import { StoryPanel } from "./StoryPanel";
import { Icon } from "./m3";
import { STORY } from "../data/story";
import { useConsole } from "../state/useConsole";

// Beginner-first layout. Story mode: board + walkthrough sheet, nothing else.
// Explore mode: rail + board + inspector with plain-English labels.
// Judge Overlay, Recording Mode, and cluster controls only exist behind Advanced.
// Gmail-style shell: chrome sits directly on the body background; the board is
// the hero card. The demo's live edge is 14:35:31.418 UTC; past mode shows that
// minus the offset.
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
    <div className={`relative flex h-full min-w-[1180px] flex-col ${recording && advanced ? "recording" : ""}`}>
      <TopBar />
      {showScrubber && <AostScrubber />}

      <div className="flex min-h-0 flex-1 gap-3 px-3 pb-3">
        {!story && (
          <div className="min-h-0 w-[280px] shrink-0 overflow-y-auto">
            <LeftRail />
          </div>
        )}
        <main className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-md3-lg bg-surface">
          <ProvenanceBoard />
          {/* Judge chips dock bottom-leading inside the board card so they can
              never occlude the rail or the inspector */}
          {advanced && <JudgeOverlay />}
          {/* Past-mode wash over the board card only */}
          {pastMode && (
            <div
              className="pointer-events-none absolute inset-0 z-10"
              style={{ background: "color-mix(in srgb, var(--md-primary) 6%, transparent)" }}
            >
              {/* top-14 clears the board card's header row */}
              <div className="absolute left-1/2 top-14 flex h-9 -translate-x-1/2 items-center gap-2 rounded-full bg-secondary-container px-4 text-on-secondary-container shadow-elevation-1">
                <Icon name="history" size={18} />
                <span className="whitespace-nowrap text-label-lg font-medium">
                  Viewing the past: {Math.abs(aostHours)}h ago
                </span>
                <span className="mono whitespace-nowrap text-label-md">({aostClock(aostHours)} UTC)</span>
              </div>
            </div>
          )}
        </main>
        {!story && (
          <div className="w-[360px] shrink-0 overflow-y-auto rounded-md3-lg bg-surface">
            <Inspector />
          </div>
        )}
      </div>

      {story && <StoryPanel />}

      {/* The activity strip earns its place once there is activity to show:
          in the story it appears with the recant step's receipt, not as noise
          on the first-run frame. */}
      {(!story || storyStep >= 3) && (
        <div className="flex h-10 shrink-0 items-center gap-4 px-4">
          <ChangefeedTicker />
          {advanced && <ClusterBar />}
        </div>
      )}
    </div>
  );
}

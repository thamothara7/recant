import { useEffect, useState } from "react";
import { TopBar } from "./TopBar";
import { AostScrubber } from "./AostScrubber";
import { LeftRail } from "./LeftRail";
import { ProvenanceBoard } from "./ProvenanceBoard";
import { Inspector } from "./Inspector";
import { ChangefeedTicker } from "./ChangefeedTicker";
import { ClusterBar } from "./ClusterBar";
import { JudgeOverlay } from "./JudgeOverlay";
import { StoryPanel } from "./StoryPanel";
import { Button, Icon } from "./m3";
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

// One-time hint shown on first Explore visit. Stored in localStorage.
const HINT_KEY = "recant-explore-hint-dismissed";
function useExploreHint() {
  const [show, setShow] = useState(false);
  const mode = useConsole((s) => s.mode);
  const hasSelection = useConsole((s) => !!(s.selectedBelief || s.selectedSource));
  useEffect(() => {
    if (mode === "explore" && !hasSelection && !localStorage.getItem(HINT_KEY)) {
      setShow(true);
    } else {
      setShow(false);
    }
  }, [mode, hasSelection]);
  const dismiss = () => {
    localStorage.setItem(HINT_KEY, "1");
    setShow(false);
  };
  return { show, dismiss };
}

export function AppShell() {
  const mode = useConsole((s) => s.mode);
  const storyStep = useConsole((s) => s.storyStep);
  const advanced = useConsole((s) => s.advanced);
  const aostHours = useConsole((s) => s.aostHours);
  const pastMode = aostHours < 0;
  const recording = useConsole((s) => s.recordingMode);
  const hasSelection = useConsole((s) => !!(s.selectedBelief || s.selectedSource));
  const boardError = useConsole((s) => s.boardError);
  const live = useConsole((s) => s.live);
  // In live mode, hold the board until the first fetch resolves so the fixture
  // seed never flashes with ids that vanish a beat later.
  const loading = useConsole((s) => s.live && !s.boardLoaded);
  const hint = useExploreHint();

  const story = mode === "story";
  // The rewind slider appears once the story introduces it, and always in Explore.
  const showScrubber = !story || !!STORY[storyStep]?.aost || storyStep >= STORY.length - 2;

  return (
    <div className={`relative flex h-full min-w-[1180px] flex-col ${recording && advanced ? "recording" : ""}`}>
      <TopBar />
      {boardError && (
        <div className="mx-3 mb-2 flex items-center gap-2 rounded-md3-md bg-error-container px-4 py-2 text-on-error-container">
          <Icon name="cloud_off" size={18} />
          <span className="text-body-sm">
            Live data unavailable, showing the built-in demo. ({boardError})
          </span>
        </div>
      )}
      {showScrubber && <AostScrubber />}

      <div className="flex min-h-0 flex-1 gap-3 px-3 pb-3">
        {!story && !loading && (
          <div className="min-h-0 w-[280px] shrink-0 overflow-y-auto">
            <LeftRail />
          </div>
        )}
        <main className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-md3-lg bg-surface">
          {loading ? (
            <div className="flex h-full items-center justify-center gap-2 text-on-surface-variant">
              <Icon name="progress_activity" size={20} className="animate-spin" />
              <span className="text-body-md">Loading the live memory board</span>
            </div>
          ) : (
            <ProvenanceBoard />
          )}
          {/* Judge chips dock bottom-leading inside the board card so they can
              never occlude the rail or the inspector */}
          {advanced && <JudgeOverlay />}
          {/* One-time Explore hint for first-time visitors */}
          {hint.show && (
            <div className="absolute inset-x-0 top-14 z-20 mx-auto flex w-fit items-center gap-3 rounded-full bg-secondary-container px-5 py-2.5 text-on-secondary-container shadow-elevation-1">
              <Icon name="touch_app" size={20} />
              <span className="text-label-lg font-medium">Click any card to trace its provenance</span>
              <Button variant="text" onClick={hint.dismiss} className="ml-1">
                Got it
              </Button>
            </div>
          )}
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
        {/* The details panel earns its 360px only when something is selected;
            an always-open empty panel was the single biggest source of
            first-glance clutter in Explore. AutoFit refits the board when the
            panel appears, so cards are never guillotined. */}
        {!story && hasSelection && (
          <div className="w-[360px] shrink-0 overflow-y-auto rounded-md3-lg bg-surface">
            <Inspector />
          </div>
        )}
      </div>

      {story && <StoryPanel />}

      {/* The activity strip earns its place once there is activity to show:
          in the story it appears with the recant step's receipt, not as noise
          on the first-run frame. */}
      {(!story || storyStep >= 2) && (
        <div className="flex h-10 shrink-0 items-center gap-4 px-4">
          <ChangefeedTicker />
          {advanced && !live && <ClusterBar />}
        </div>
      )}
    </div>
  );
}

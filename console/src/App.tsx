import { useEffect, useState } from "react";
import { AppShell } from "./components/AppShell";
import { MobileSummary } from "./components/MobileSummary";
import { isStoryDone } from "./lib/storyProgress";
import { useConsole } from "./state/useConsole";

// The board needs room (skill 4: desktop-first). Below the laptop breakpoint
// the console renders the read-only incident summary instead of squeezing an
// illegible graph onto a phone.
const WIDE = "(min-width: 1024px)";
function useWide(): boolean {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches);
  useEffect(() => {
    const mq = window.matchMedia(WIDE);
    const onChange = (e: MediaQueryListEvent) => setWide(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return wide;
}

// Keyboard. Always: arrow keys step the story. Advanced only: J toggles the
// Judge Overlay, V toggles Recording Mode, R resets, 1-6 fire the proof moments
// (skill 5). Ignored while typing in a field.
export function App() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      // Leave browser/OS chords (Cmd+R, Ctrl+1, ...) alone.
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const s = useConsole.getState();
      if (s.mode === "story") {
        if (e.key === "ArrowRight") return s.nextStep();
        if (e.key === "ArrowLeft") return s.prevStep();
      }
      if (!s.advanced) return;
      if (e.key === "j" || e.key === "J") s.toggleOverlay();
      else if (e.key === "v" || e.key === "V") s.toggleRecording();
      else if (e.key === "r" || e.key === "R") s.reset();
      else if (e.key >= "1" && e.key <= "6") s.runMoment(Number(e.key));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // First visit: start the walkthrough at step 1. A browser that already
  // finished it (localStorage flag) opens straight into Explore; the Story
  // tab replays the walkthrough on demand. Live mode always opens in Explore
  // (Story is the scripted fixtures) and fetches the real board.
  useEffect(() => {
    const s = useConsole.getState();
    if (s.live) {
      s.setMode("explore");
      void s.loadBoard();
    } else if (isStoryDone()) {
      s.setMode("explore");
    } else {
      s.setStoryStep(0);
    }
  }, []);

  const wide = useWide();

  return (
    <div className="h-full">
      {wide ? <AppShell /> : <MobileSummary />}
    </div>
  );
}

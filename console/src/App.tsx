import { useEffect } from "react";
import { AppShell } from "./components/AppShell";
import { useConsole } from "./state/useConsole";

// Keyboard: J toggles the Judge Overlay, V toggles Recording Mode, R resets,
// 1-6 fire the proof moments (skill 5). Ignored while typing in a field.
export function App() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      // Leave browser/OS chords (Cmd+R, Ctrl+1, ...) alone.
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const s = useConsole.getState();
      if (e.key === "j" || e.key === "J") s.toggleOverlay();
      else if (e.key === "v" || e.key === "V") s.toggleRecording();
      else if (e.key === "r" || e.key === "R") s.reset();
      else if (e.key >= "1" && e.key <= "6") s.runMoment(Number(e.key));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="h-full">
      <AppShell />
    </div>
  );
}

import { useEffect, useState } from "react";
import { useConsole } from "../state/useConsole";
import { Icon, IconButton } from "./m3";

// Product chrome stays product chrome: brand, Story/Explore switch, theme,
// Advanced. The judge-facing demo machinery (moments 1-6, overlay, recording)
// lives in its own docked strip below the app bar, only when Advanced is on,
// so the app bar never reads as a keyboard-macro palette.
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

  // Theme is local, not zustand: it must survive story resets.
  const [dark, setDark] = useState(false);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "";
  }, [dark]);

  return (
    <>
      <header className="flex h-16 shrink-0 items-center justify-between px-4">
        <div className="flex items-center gap-3">
          <div className="grid h-8 w-8 place-items-center rounded-md3-sm bg-primary text-on-primary">
            <span className="text-label-lg font-medium">R</span>
          </div>
          <div className="text-title-lg text-on-surface">Recant</div>
        </div>

        <div className="flex items-center gap-2">
          {/* Story / Explore switch: M3 segmented button */}
          <div
            role="tablist"
            aria-label="View mode"
            className="flex h-10 divide-x divide-outline overflow-hidden rounded-full border border-outline"
          >
            {(["story", "explore"] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={`state-layer flex h-full items-center gap-2 px-5 text-label-lg font-medium ${
                  mode === m
                    ? "bg-secondary-container text-on-secondary-container"
                    : "text-on-surface"
                }`}
              >
                {mode === m && <Icon name="check" size={16} />}
                {m === "story" ? "Story" : "Explore"}
              </button>
            ))}
          </div>

          <IconButton
            icon={dark ? "light_mode" : "dark_mode"}
            label="Toggle theme"
            onClick={() => setDark((d) => !d)}
          />

          <PillToggle label="Advanced" on={advanced} onClick={toggleAdvanced} offIcon="tune" />
        </div>
      </header>

      {advanced && <DemoStrip />}
    </>
  );
}

// The Demo Director, docked under the app bar: proof moments 1-6, reset, and
// the Judge/Recording toggles. Submission machinery, deliberately separate
// from the product chrome.
function DemoStrip() {
  const overlayOn = useConsole((s) => s.overlayOn);
  const recordingMode = useConsole((s) => s.recordingMode);
  const toggleOverlay = useConsole((s) => s.toggleOverlay);
  const toggleRecording = useConsole((s) => s.toggleRecording);
  const runMoment = useConsole((s) => s.runMoment);
  const reset = useConsole((s) => s.reset);

  return (
    <div className="flex h-11 shrink-0 items-center gap-2 px-4">
      <span className="text-label-md font-medium text-on-surface-variant">Demo</span>
      <div className="flex items-center gap-1.5">
        {MOMENTS.map((m) => (
          <button
            key={m.n}
            onClick={() => runMoment(m.n)}
            className="state-layer flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md3-sm border border-outline-variant px-2.5 text-label-md font-medium text-on-surface-variant"
          >
            <span className="mono text-on-surface-variant">{m.n}</span>
            {m.label}
          </button>
        ))}
        <button
          onClick={reset}
          aria-label="Reset the demo"
          title="Reset the demo (R)"
          className="state-layer flex h-8 w-8 items-center justify-center rounded-md3-sm border border-outline-variant text-on-surface-variant"
        >
          <Icon name="restart_alt" size={16} />
        </button>
      </div>
      <span aria-hidden className="mx-1 h-5 w-px bg-outline-variant" />
      <PillToggle label="Judge overlay" hint="J" on={overlayOn} onClick={toggleOverlay} small />
      <PillToggle
        label="Recording"
        hint="V"
        on={recordingMode}
        onClick={toggleRecording}
        tone="recording"
        small
      />
    </div>
  );
}

// M3 pill toggle: outlined at rest, tonal when on. Recording tone flips the on
// state to the error container so a live capture is unmistakable.
function PillToggle({
  label,
  on,
  onClick,
  hint,
  offIcon,
  tone = "default",
  small = false,
}: {
  label: string;
  on: boolean;
  onClick: () => void;
  hint?: string;
  offIcon?: string;
  tone?: "default" | "recording";
  small?: boolean;
}) {
  const onClasses =
    tone === "recording"
      ? "bg-error-container text-on-error-container"
      : "bg-secondary-container text-on-secondary-container";
  const onIcon = tone === "recording" ? "radio_button_checked" : "check";
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={`state-layer flex items-center gap-2 whitespace-nowrap rounded-full border border-outline font-medium ${
        small ? "h-8 px-3 text-label-md" : "h-10 px-4 text-label-lg"
      } ${on ? onClasses : "text-on-surface-variant"}`}
    >
      {on ? (
        <Icon name={onIcon} size={16} />
      ) : offIcon ? (
        <Icon name={offIcon} size={16} />
      ) : null}
      {label}
      {hint && <span className="mono text-label-sm">{hint}</span>}
    </button>
  );
}

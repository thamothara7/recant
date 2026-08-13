import { useConsole } from "../state/useConsole";
import { Button, Chip, Icon } from "./m3";

// The time rewind (AS OF SYSTEM TIME underneath). 0 = now; dragging back shows
// the board exactly as it was then. Plain words; the SQL lives in the Judge
// Overlay for Advanced viewers.
const MARKS = [-6, -5, -4, -3, -2, -1, 0];

export function AostScrubber() {
  const aost = useConsole((s) => s.aostHours);
  const setAost = useConsole((s) => s.setAost);
  const live = aost === 0;

  return (
    <div className="flex h-12 items-center gap-3 px-6">
      <Icon name="history" size={18} className="text-on-surface-variant" />
      <span className="whitespace-nowrap text-label-lg font-medium text-on-surface-variant">Rewind time</span>

      <div className="relative min-w-0 flex-1">
        <input
          type="range"
          min={-6}
          max={0}
          step={1}
          value={aost}
          onChange={(e) => setAost(Number(e.target.value))}
          aria-label="How many hours to rewind"
          aria-valuetext={live ? "Live" : `${-aost} hours ago`}
          className="aost-range w-full"
        />
        <div className="pointer-events-none mt-1 flex justify-between">
          {MARKS.map((m) => (
            <span key={m} className="text-label-md font-medium text-on-surface-variant">
              {m === 0 ? "now" : `${-m}h ago`}
            </span>
          ))}
        </div>
      </div>

      {/* Reserve the same trailing width in both states. Without this fixed
          slot, showing "Back to now" shortens the range and makes the thumb
          and every hour marker jump as soon as the user rewinds. */}
      <div className="flex w-48 shrink-0 items-center justify-end gap-1">
        {live ? (
          <Chip label="Live" />
        ) : (
          <>
            <Chip
              label={`${-aost}h ago`}
              container="var(--md-secondary-container)"
              onContainer="var(--md-on-secondary-container)"
            />
            <Button variant="text" onClick={() => setAost(0)}>
              Back to now
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

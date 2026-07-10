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

      <div className="relative flex-1">
        <input
          type="range"
          min={-6}
          max={0}
          step={1}
          value={aost}
          onChange={(e) => setAost(Number(e.target.value))}
          aria-label="How many hours to rewind"
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

      {/* At the live edge the chip says it all; a disabled ghost button would
          just read as broken text in a paused frame. */}
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
  );
}

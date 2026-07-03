import { POISONED_SOURCE, STORY } from "../data/story";
import { useConsole } from "../state/useConsole";

// The guided walkthrough strip (beginner-first redesign). One idea per step,
// plain English, big Back/Next. The board above illustrates what the text says.
export function StoryPanel() {
  const step = useConsole((s) => s.storyStep);
  const next = useConsole((s) => s.nextStep);
  const prev = useConsole((s) => s.prevStep);
  const setMode = useConsole((s) => s.setMode);
  const recant = useConsole((s) => s.recant);
  const recanting = useConsole((s) => s.recanting);
  const recanted = useConsole((s) => s.recantedSource === POISONED_SOURCE);

  const s = STORY[step];
  const first = step === 0;
  const last = step === STORY.length - 1;

  return (
    <section
      aria-label="Guided walkthrough"
      className="shrink-0 border-t border-hairline bg-[var(--ink-2)] px-6 py-4"
    >
      <div className="mx-auto flex max-w-[980px] items-center gap-6">
        {/* progress */}
        <div className="w-[92px] shrink-0">
          <div className="font-ui text-[12px] font-medium text-bond-dim">
            Step {step + 1} of {STORY.length}
          </div>
          <div className="mt-1.5 flex gap-1" aria-hidden>
            {STORY.map((_, i) => (
              <span
                key={i}
                className="h-1 flex-1 rounded-full"
                style={{ background: i <= step ? "var(--uv)" : "var(--hairline-strong)" }}
              />
            ))}
          </div>
        </div>

        {/* narration */}
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-[18px] leading-tight text-bond">{s.title}</h2>
          <p className="mt-1 font-ui text-[13.5px] leading-relaxed text-bond-dim">{s.body}</p>
        </div>

        {/* the one big action on the recant step */}
        {s.cta && (
          <button
            onClick={() => recant(POISONED_SOURCE)}
            disabled={recanting || recanted}
            className="shrink-0 rounded-panel px-4 py-3 font-ui text-[14px] font-semibold transition-colors disabled:cursor-default"
            style={{
              background: recanted ? "transparent" : "var(--quarantined)",
              color: recanted ? "var(--attested)" : "#fff",
              border: `1px solid ${recanted ? "color-mix(in srgb, var(--attested) 50%, transparent)" : "var(--quarantined)"}`,
              opacity: recanting ? 0.7 : 1,
            }}
          >
            {recanted ? "✓ Taken back" : recanting ? "Taking it back…" : "Take back the bad fact"}
          </button>
        )}

        {/* navigation */}
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={prev}
            disabled={first}
            className="rounded-panel border border-hairline px-4 py-3 font-ui text-[14px] text-bond-dim transition-colors hover:text-bond disabled:opacity-35"
          >
            ◀ Back
          </button>
          {last ? (
            <button
              onClick={() => setMode("explore")}
              className="rounded-panel px-5 py-3 font-ui text-[14px] font-semibold text-[#0e0b1f] transition-opacity hover:opacity-90"
              style={{ background: "var(--uv)" }}
            >
              Start exploring
            </button>
          ) : (
            <button
              onClick={next}
              className="rounded-panel px-5 py-3 font-ui text-[14px] font-semibold text-[#0e0b1f] transition-opacity hover:opacity-90"
              style={{ background: "var(--uv)" }}
            >
              Next ▶
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

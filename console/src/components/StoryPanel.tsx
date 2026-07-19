import { POISONED_SOURCE, STORY } from "../data/story";
import { markStoryDone } from "../lib/storyProgress";
import { useConsole } from "../state/useConsole";
import { Button, Icon } from "./m3";

// The guided walkthrough sheet (beginner-first redesign). One idea per step,
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
      className="mx-3 mb-3 shrink-0 rounded-md3-lg bg-surface px-6 py-5"
    >
      <div className="mx-auto flex max-w-[980px] items-center gap-6">
        {/* progress */}
        <div className="w-[92px] shrink-0">
          <div className="text-label-md font-medium text-on-surface-variant">
            Step {step + 1} of {STORY.length}
          </div>
          <div className="mt-1.5 flex gap-1" aria-hidden>
            {STORY.map((_, i) => (
              <span
                key={i}
                className={`h-1 flex-1 rounded-full ${
                  i <= step ? "bg-primary" : "bg-surface-container-highest"
                }`}
              />
            ))}
          </div>
        </div>

        {/* narration */}
        <div className="min-w-0 flex-1">
          {/* Scenario context shown on the first step only */}
          {s.scenario && (
            <div className="mb-1 flex items-center gap-1.5 text-label-md font-medium text-on-surface-variant">
              <Icon name="smart_toy" size={14} />
              {s.scenario}
            </div>
          )}
          <h2 className="text-title-lg text-on-surface">{s.title}</h2>
          <p className="mt-1 text-body-md text-on-surface-variant">{s.body}</p>
        </div>

        {/* the one big action on the recant step */}
        {s.cta &&
          (recanted ? (
            <Button variant="tonal" icon="check_circle" disabled className="shrink-0">
              Taken back
            </Button>
          ) : (
            <Button
              variant="filled"
              tone="error"
              icon="block"
              disabled={recanting}
              onClick={() => recant(POISONED_SOURCE)}
              className="shrink-0"
            >
              {recanting ? "Taking it back..." : "Take back the bad fact"}
            </Button>
          ))}

        {/* navigation. One filled button per step: while the destructive CTA is
            live it holds the emphasis and Next demotes to a text button. */}
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="text" icon="arrow_back" onClick={prev} disabled={first}>
            Back
          </Button>
          {last ? (
            <Button
              variant="filled"
              onClick={() => {
                // Finishing the walkthrough is remembered per browser: the
                // next visit opens in Explore (App.tsx reads the flag).
                markStoryDone();
                setMode("explore");
              }}
            >
              Start exploring
            </Button>
          ) : (
            <Button
              variant={s.cta && !recanted ? "text" : "filled"}
              icon="arrow_forward"
              onClick={next}
              className={first ? "story-pulse" : ""}
            >
              Next
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

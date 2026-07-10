import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AGENTS, BELIEFS, SOURCES, taintClosure } from "../data/fixtures";
import { useConsole } from "../state/useConsole";
import { Icon } from "./m3";

const agentName = (id: string) => AGENTS.find((a) => a.id === id)?.name ?? id;

// The one big action in the console, in plain words: say exactly what will be
// blocked, show the list, ask for one clear confirmation. (The old typed-id
// confirmation was beginner-hostile; the blast radius is still named exactly.)
export function RecantDialog({ sourceId }: { sourceId: string }) {
  const [open, setOpen] = useState(false);
  const recant = useConsole((s) => s.recant);
  const already = useConsole((s) => s.recantedSource === sourceId);

  const src = SOURCES.find((s) => s.id === sourceId)!;
  const closure = taintClosure(sourceId);
  const affected = BELIEFS.filter((b) => closure.includes(b.id));
  const bots = new Set(affected.map((b) => b.agentId));

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        {/* Native button (not the m3 Button component) so Radix can attach its
            trigger ref for focus return on close; the classes mirror the m3
            Button recipe exactly (filled/error live, tonal when already done). */}
        <button
          disabled={already}
          className={`state-layer mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-full pl-4 pr-6 text-label-lg font-medium transition-colors ${
            already
              ? "pointer-events-none bg-secondary-container text-on-secondary-container opacity-40"
              : "bg-error text-on-error"
          }`}
        >
          <Icon name={already ? "check_circle" : "block"} size={18} />
          {already ? "Already taken back" : "Take back everything from this source"}
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim opacity-40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-[440px] -translate-x-1/2 -translate-y-1/2 rounded-md3-xl bg-surface-container-high p-6 shadow-elevation-3"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <div className="grid place-items-center text-secondary">
            <Icon name="gpp_maybe" size={24} />
          </div>
          <Dialog.Title className="mt-3 text-center text-headline-sm text-on-surface">
            Take back this bad fact?
          </Dialog.Title>
          {/* Inline emphasis by weight, never hue (M3 voice): color inside body
              copy is reserved for the confirm action itself. */}
          <Dialog.Description className="mt-2 text-body-md text-on-surface-variant">
            Recant will block{" "}
            <span className="font-medium text-on-surface">
              {closure.length} memories across {bots.size} bots
            </span>{" "}
            at the same time, including reworded copies that never linked back to the source.
          </Dialog.Description>

          <div className="mt-3 rounded-md3-sm bg-surface-container-highest px-3 py-2 text-body-sm text-on-surface-variant">
            Source: <span className="text-on-surface">{src.label}</span>{" "}
            <span className="font-medium">(not trusted)</span>
            <span className="mono block text-label-sm">{src.uri}</span>
          </div>

          <ul className="mt-3 flex max-h-[180px] flex-col gap-1.5 overflow-y-auto">
            {affected.map((b) => (
              <li key={b.id} className="rounded-md3-sm bg-surface-container-highest px-3 py-2">
                <div className="text-body-sm text-on-surface">{b.content}</div>
                <div className="mt-0.5 text-label-sm text-on-surface-variant">{agentName(b.agentId)}</div>
              </li>
            ))}
          </ul>

          <div className="mt-6 flex items-center justify-end gap-2">
            <Dialog.Close asChild>
              {/* Native button under Radix Close for the same ref reason;
                  mirrors the m3 text Button recipe. */}
              <button className="state-layer inline-flex h-10 items-center justify-center rounded-full px-6 text-label-lg font-medium text-primary">
                Cancel
              </button>
            </Dialog.Close>
            {/* Verb-phrase label (no "Yes," prefix); tonal error keeps the
                destructive weight without a filled button inside a dialog. */}
            <button
              onClick={() => {
                recant(sourceId);
                setOpen(false);
              }}
              className="state-layer inline-flex h-10 items-center justify-center gap-2 rounded-full bg-error-container px-6 text-label-lg font-medium text-on-error-container"
            >
              Block {closure.length} memories
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

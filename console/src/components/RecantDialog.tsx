import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AGENTS, BELIEFS, SOURCES, taintClosure } from "../data/fixtures";
import { useConsole } from "../state/useConsole";

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
        <button
          disabled={already}
          className="mt-3 w-full rounded-tag border px-3 py-2 font-ui text-[12.5px] font-medium transition-colors disabled:opacity-50"
          style={{
            borderColor: already ? "var(--hairline)" : "var(--quarantined)",
            color: already ? "var(--bond-dim)" : "var(--quarantined)",
            background: already ? "transparent" : "color-mix(in srgb, var(--quarantined) 10%, transparent)",
          }}
        >
          {already ? "✓ Already taken back" : "Take back everything from this source"}
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(6,10,16,.66)] backdrop-blur-[1px]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-[460px] -translate-x-1/2 -translate-y-1/2 rounded-panel border border-hairline-strong bg-panel p-5 shadow-drawer"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <Dialog.Title className="font-display text-[19px] text-bond">Take back this bad fact?</Dialog.Title>
          <Dialog.Description className="mt-2 font-ui text-[13px] leading-relaxed text-bond-dim">
            Recant will block{" "}
            <span style={{ color: "var(--quarantined)" }}>
              {closure.length} memories across {bots.size} bots
            </span>{" "}
            at the same time — including reworded copies that never linked back to the source.
          </Dialog.Description>

          <div className="mt-3 rounded-tag border border-hairline bg-[var(--ink-2)] px-3 py-2 font-ui text-[12px] text-bond-dim">
            Source: <span className="text-bond">{src.label}</span>{" "}
            <span style={{ color: "var(--quarantined)" }}>(not trusted)</span>
            <span className="mono text-[10px]"> · {src.uri}</span>
          </div>

          <ul className="mt-3 flex max-h-[180px] flex-col gap-1.5 overflow-y-auto">
            {affected.map((b) => (
              <li key={b.id} className="rounded-tag border border-hairline bg-[var(--ink-2)] px-2.5 py-1.5">
                <div className="font-ui text-[11.5px] text-bond">{b.content}</div>
                <div className="mt-0.5 font-ui text-[10px] text-bond-dim">{agentName(b.agentId)}</div>
              </li>
            ))}
          </ul>

          <div className="mt-4 flex justify-end gap-2">
            <Dialog.Close asChild>
              <button className="rounded-tag px-3 py-2 font-ui text-[13px] text-bond-dim hover:text-bond">
                Cancel
              </button>
            </Dialog.Close>
            <button
              onClick={() => {
                recant(sourceId);
                setOpen(false);
              }}
              className="rounded-tag px-4 py-2 font-ui text-[13px] font-semibold transition-colors"
              style={{
                background: "var(--quarantined)",
                color: "#fff",
                border: "1px solid var(--quarantined)",
              }}
            >
              Yes — block {closure.length} memories
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

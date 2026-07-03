import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { BELIEFS, SOURCES, taintClosure } from "../data/fixtures";
import { useConsole } from "../state/useConsole";

// The one destructive action in the console. Typed confirmation, evidence-room
// copy: name the exact blast radius and require the operator to type the id.
export function RecantDialog({ sourceId }: { sourceId: string }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const recant = useConsole((s) => s.recant);
  const already = useConsole((s) => s.recantedSource === sourceId);

  const src = SOURCES.find((s) => s.id === sourceId)!;
  const closure = taintClosure(sourceId);
  const agents = new Set(BELIEFS.filter((b) => closure.includes(b.id)).map((b) => b.agentId));
  const armed = typed.trim() === sourceId;

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
          {already ? "Source recanted" : "Recant source"}
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[rgba(6,10,16,.66)] backdrop-blur-[1px]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-[440px] -translate-x-1/2 -translate-y-1/2 rounded-panel border border-hairline-strong bg-panel p-5 shadow-drawer"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <Dialog.Title className="font-display text-[19px] text-bond">Recant a source</Dialog.Title>
          <Dialog.Description className="mt-2 font-ui text-[13px] leading-relaxed text-bond-dim">
            This quarantines{" "}
            <span className="text-bond" style={{ color: "var(--quarantined)" }}>
              {closure.length} beliefs across {agents.size} agents
            </span>{" "}
            in one serializable transaction, including paraphrases matched only by
            vector proximity. Type the source id{" "}
            <span className="mono text-bond">{sourceId}</span> to proceed.
          </Dialog.Description>

          <div className="mt-3 rounded-tag border border-hairline bg-[var(--ink-2)] px-3 py-2 mono text-[11px] text-bond-dim">
            {src.label} · <span style={{ color: "var(--quarantined)" }}>{src.trust}</span> · {src.uri}
          </div>

          <input
            autoFocus
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && armed && (recant(sourceId), setOpen(false))}
            placeholder={sourceId}
            spellCheck={false}
            className="mt-3 w-full rounded-tag border border-hairline bg-[var(--ink-2)] px-3 py-2 mono text-[12px] text-bond outline-none placeholder:text-bond-dim/50 focus:border-uv"
          />

          <div className="mt-4 flex justify-end gap-2">
            <Dialog.Close asChild>
              <button className="rounded-tag px-3 py-1.5 font-ui text-[12.5px] text-bond-dim hover:text-bond">
                Cancel
              </button>
            </Dialog.Close>
            <button
              disabled={!armed}
              onClick={() => {
                recant(sourceId);
                setOpen(false);
              }}
              className="rounded-tag px-3 py-1.5 font-ui text-[12.5px] font-medium transition-colors disabled:opacity-40"
              style={{
                background: armed ? "var(--quarantined)" : "transparent",
                color: armed ? "#120a0b" : "var(--bond-dim)",
                border: `1px solid ${armed ? "var(--quarantined)" : "var(--hairline)"}`,
              }}
            >
              Recant {closure.length} beliefs
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

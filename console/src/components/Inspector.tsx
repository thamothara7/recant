import type { ReactNode } from "react";
import {
  AGENTS,
  BELIEFS,
  DERIVATIONS,
  INCIDENT,
  SOURCES,
  taintClosure,
} from "../data/fixtures";
import type { Belief } from "../data/types";
import { HashChip } from "./HashChip";
import { StatusBadge } from "./StatusBadge";
import { RecantDialog } from "./RecantDialog";
import { STATUS_EXPLAIN, TRUST_META, clockUtc } from "../lib/format";
import { useConsole, useDisplayStatuses } from "../state/useConsole";

const agentName = (id: string) => AGENTS.find((a) => a.id === id)?.name ?? id;
const beliefById = (id: string) => BELIEFS.find((b) => b.id === id);
const incidentClosure = taintClosure(INCIDENT.sourceId);

// Plain-English details panel (beginner-first redesign). Answers, in order:
// what does this memory say, is it OK, where did it come from, where did it
// spread. Hashes/signatures/regions only appear with the Advanced toggle.
export function Inspector() {
  const selectedBelief = useConsole((s) => s.selectedBelief);
  const selectedSource = useConsole((s) => s.selectedSource);
  const statuses = useDisplayStatuses();

  const belief = selectedBelief ? beliefById(selectedBelief) : null;

  return (
    <aside className="flex w-[360px] shrink-0 flex-col overflow-y-auto border-l border-hairline bg-[var(--ink-2)]">
      <header className="border-b border-hairline px-4 py-2">
        <h2 className="label">{belief ? "Memory details" : selectedSource ? "Source details" : "Details"}</h2>
      </header>

      <div className="flex-1 px-4 py-4">
        {belief ? (
          <BeliefInspector belief={belief} status={statuses[belief.id] ?? belief.status} />
        ) : selectedSource ? (
          <SourceInspector sourceId={selectedSource} />
        ) : (
          <Empty />
        )}
      </div>
    </aside>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="label">{label}</span>
      <span className="text-right font-ui text-[12px] text-bond">{children}</span>
    </div>
  );
}

function ChainRow({
  marker,
  title,
  detail,
  tone = "bond",
}: {
  marker: string;
  title: ReactNode;
  detail?: ReactNode;
  tone?: "bond" | "uv";
}) {
  return (
    <li className="relative pl-5">
      <span
        className="absolute left-0 top-[3px] mono text-[10px]"
        style={{ color: tone === "uv" ? "var(--uv)" : "var(--bond-dim)" }}
      >
        {marker}
      </span>
      <div className="font-ui text-[12px] text-bond">{title}</div>
      {detail && <div className="mt-0.5 font-ui text-[10.5px] text-bond-dim">{detail}</div>}
    </li>
  );
}

function BeliefInspector({ belief, status }: { belief: Belief; status: Belief["status"] }) {
  const advanced = useConsole((s) => s.advanced);
  const src = belief.sourceId ? SOURCES.find((s) => s.id === belief.sourceId) : null;
  const parents = DERIVATIONS.filter((d) => d.childId === belief.id);
  const children = DERIVATIONS.filter((d) => d.parentId === belief.id);
  const inIncident = incidentClosure.includes(belief.id);

  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="font-ui text-[11px] font-medium uppercase tracking-[0.1em] text-bond-dim">
          {agentName(belief.agentId)} · memory #{belief.seq}
        </span>
        <StatusBadge status={status} />
      </div>

      <p className="mt-2 font-display text-[16px] leading-snug text-bond">{belief.content}</p>
      <p className="mt-1.5 font-ui text-[11.5px] leading-relaxed text-bond-dim">{STATUS_EXPLAIN[status]}</p>

      <Divider label="Where it came from" />
      <ol className="flex flex-col gap-2.5">
        <ChainRow
          marker="1"
          title={src ? src.label : "Built from other memories"}
          detail={src ? `${TRUST_META[src.trust].label} source · ${src.uri}` : "see the memories it was based on below"}
          tone={src?.trust === "untrusted" ? "uv" : "bond"}
        />
        <ChainRow
          marker="2"
          title={`Saved and signed by the ${agentName(belief.agentId)}`}
          detail={
            advanced ? (
              <HashChip hash={belief.sig.replace("…", belief.hash.slice(8, 24))} label="ed25519" />
            ) : (
              "the signature proves nobody edited it afterwards"
            )
          }
        />
        {parents.length > 0 ? (
          parents.map((p) => {
            const pb = beliefById(p.parentId);
            return (
              <ChainRow
                key={p.parentId}
                marker="3"
                title={<>Based on: “{pb ? pb.content : p.parentId}”</>}
                detail={
                  p.kind === "inferred"
                    ? `reworded copy — found by meaning match (${Math.round(p.score * 100)}% similar)`
                    : "copied directly, with a link back"
                }
                tone={p.kind === "inferred" ? "uv" : "bond"}
              />
            );
          })
        ) : (
          <ChainRow marker="3" title="This bot's first note on the topic" detail="not based on any earlier memory" />
        )}
      </ol>

      {children.length > 0 && (
        <>
          <Divider label={`It spread to ${children.length} other ${children.length === 1 ? "memory" : "memories"}`} />
          <ul className="flex flex-col gap-2">
            {children.map((c) => {
              const cb = beliefById(c.childId);
              return (
                <li key={c.childId} className="rounded-tag border border-hairline bg-panel px-2.5 py-1.5">
                  <div className="font-ui text-[11.5px] text-bond">{cb?.content}</div>
                  <div className="mt-0.5 font-ui text-[10px] text-bond-dim">
                    {agentName(cb?.agentId ?? "")} ·{" "}
                    {c.kind === "inferred"
                      ? `reworded copy (${Math.round(c.score * 100)}% similar)`
                      : "copied directly"}
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {advanced && (
        <>
          <Divider label="Technical record" />
          <Field label="Hash">
            <HashChip hash={belief.hash} />
          </Field>
          <Field label="Prev">
            <HashChip hash={belief.prevHash} />
          </Field>
          <Field label="Created">
            <span className="mono text-[11px]">{clockUtc(belief.createdAt)} UTC</span>
          </Field>
          <Field label="Region">
            <span className="mono text-[11px]">{belief.region}</span>
          </Field>
        </>
      )}

      {inIncident && <IncidentPanel />}
    </div>
  );
}

function SourceInspector({ sourceId }: { sourceId: string }) {
  const src = SOURCES.find((s) => s.id === sourceId)!;
  const own = BELIEFS.filter((b) => b.sourceId === sourceId);
  const isIncident = sourceId === INCIDENT.sourceId;

  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="font-ui text-[11px] font-medium uppercase tracking-[0.1em] text-bond-dim">source</span>
        <span
          className="font-ui text-[11px] font-medium"
          style={{ color: TRUST_META[src.trust].token }}
        >
          {TRUST_META[src.trust].label}
        </span>
      </div>
      <p className="mt-2 font-display text-[17px] text-bond">{src.label}</p>
      <p className="mono text-[11px] text-bond-dim">{src.uri}</p>

      <Divider label={`Memories that came from here (${own.length})`} />
      <ul className="flex flex-col gap-2">
        {own.map((b) => (
          <li key={b.id} className="rounded-tag border border-hairline bg-panel px-2.5 py-1.5">
            <div className="font-ui text-[11.5px] text-bond">{b.content}</div>
            <div className="mt-0.5 font-ui text-[10px] text-bond-dim">{agentName(b.agentId)} · memory #{b.seq}</div>
          </li>
        ))}
      </ul>

      {isIncident && <IncidentPanel />}
    </div>
  );
}

function IncidentPanel() {
  return (
    <div className="mt-5 rounded-panel border border-[color-mix(in_srgb,var(--quarantined)_45%,transparent)] bg-[color-mix(in_srgb,var(--quarantined)_7%,var(--panel))] p-3">
      <div className="flex items-center justify-between">
        <span className="label" style={{ color: "var(--quarantined)" }}>
          Bad source alert
        </span>
        <span className="mono text-[10px] text-bond-dim">{INCIDENT.id}</span>
      </div>
      <p className="mt-1.5 font-ui text-[12px] leading-relaxed text-bond">{INCIDENT.summary}</p>
      <RecantDialog sourceId={INCIDENT.sourceId} />
    </div>
  );
}

function Divider({ label }: { label: string }) {
  return (
    <div className="mb-2.5 mt-5 flex items-center gap-2">
      <span className="label whitespace-nowrap">{label}</span>
      <span className="h-px flex-1 bg-hairline" />
    </div>
  );
}

function Empty() {
  return (
    <div className="mt-10 text-center">
      <p className="font-ui text-[13px] text-bond-dim">
        Click any memory card on the board — or a source on the left — to see its full story.
      </p>
    </div>
  );
}

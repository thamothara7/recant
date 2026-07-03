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
import { clockUtc } from "../lib/format";
import { useConsole } from "../state/useConsole";

const agentName = (id: string) => AGENTS.find((a) => a.id === id)?.name ?? id;
const beliefById = (id: string) => BELIEFS.find((b) => b.id === id);
const incidentClosure = taintClosure(INCIDENT.sourceId);

export function Inspector() {
  const selectedBelief = useConsole((s) => s.selectedBelief);
  const selectedSource = useConsole((s) => s.selectedSource);
  const statuses = useConsole((s) => s.statuses);

  const belief = selectedBelief ? beliefById(selectedBelief) : null;

  return (
    <aside className="flex w-[360px] shrink-0 flex-col overflow-y-auto border-l border-hairline bg-[var(--ink-2)]">
      <header className="border-b border-hairline px-4 py-2">
        <h2 className="label">Inspector</h2>
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
      {detail && <div className="mt-0.5 mono text-[10px] text-bond-dim">{detail}</div>}
    </li>
  );
}

function BeliefInspector({ belief, status }: { belief: Belief; status: Belief["status"] }) {
  const src = belief.sourceId ? SOURCES.find((s) => s.id === belief.sourceId) : null;
  const parents = DERIVATIONS.filter((d) => d.childId === belief.id);
  const children = DERIVATIONS.filter((d) => d.parentId === belief.id);
  const inIncident = incidentClosure.includes(belief.id);

  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="mono text-[11px] uppercase tracking-[0.12em] text-bond-dim">
          {agentName(belief.agentId)} · belief #{belief.seq}
        </span>
        <StatusBadge status={status} />
      </div>

      <p className="mt-2 font-display text-[16px] leading-snug text-bond">{belief.content}</p>

      <Divider label="Custody chain" />
      <ol className="flex flex-col gap-2.5">
        <ChainRow
          marker="§"
          title={src ? src.label : "Derived belief (no source)"}
          detail={src ? `${src.trust} · ${src.uri}` : "provenance is upstream beliefs"}
          tone={src?.trust === "untrusted" ? "uv" : "bond"}
        />
        <ChainRow
          marker="✎"
          title={`Signed by ${agentName(belief.agentId)}`}
          detail={<HashChip hash={belief.sig.replace("…", belief.hash.slice(8, 24))} label="ed25519" />}
        />
        {parents.length > 0 ? (
          parents.map((p) => {
            const pb = beliefById(p.parentId);
            return (
              <ChainRow
                key={p.parentId}
                marker="↳"
                title={pb ? pb.content : p.parentId}
                detail={`parent · ${p.kind}${p.kind === "inferred" ? ` · cosine ${p.score}` : ""}`}
                tone={p.kind === "inferred" ? "uv" : "bond"}
              />
            );
          })
        ) : (
          <ChainRow marker="↳" title="Genesis for this agent" detail={<HashChip hash={belief.prevHash} label="prev" />} />
        )}
      </ol>

      <Divider label="Attestation" />
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

      {children.length > 0 && (
        <>
          <Divider label={`Spreads to ${children.length}`} />
          <ul className="flex flex-col gap-2">
            {children.map((c) => {
              const cb = beliefById(c.childId);
              return (
                <li key={c.childId} className="rounded-tag border border-hairline bg-panel px-2.5 py-1.5">
                  <div className="font-ui text-[11.5px] text-bond">{cb?.content}</div>
                  <div className="mt-0.5 mono text-[9px] text-bond-dim">
                    {agentName(cb?.agentId ?? "")} · {c.kind}
                    {c.kind === "inferred" ? ` · cosine ${c.score}` : ""}
                  </div>
                </li>
              );
            })}
          </ul>
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
        <span className="mono text-[11px] uppercase tracking-[0.12em] text-bond-dim">source</span>
        <span className="mono text-[11px]" style={{ color: src.trust === "untrusted" ? "var(--quarantined)" : "var(--bond-dim)" }}>
          {src.trust}
        </span>
      </div>
      <p className="mt-2 font-display text-[17px] text-bond">{src.label}</p>
      <p className="mono text-[11px] text-bond-dim">{src.uri}</p>

      <Divider label={`Beliefs from this source (${own.length})`} />
      <ul className="flex flex-col gap-2">
        {own.map((b) => (
          <li key={b.id} className="rounded-tag border border-hairline bg-panel px-2.5 py-1.5">
            <div className="font-ui text-[11.5px] text-bond">{b.content}</div>
            <div className="mt-0.5 mono text-[9px] text-bond-dim">{agentName(b.agentId)} · belief #{b.seq}</div>
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
          Open incident
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
        Select a belief on the board, or a source in the fleet rail, to read its custody chain.
      </p>
    </div>
  );
}

import type { ReactNode } from "react";
import { INCIDENT } from "../data/fixtures";
import type { Belief, Source } from "../data/types";
import type { Board } from "../lib/api";
import { HashChip } from "./HashChip";
import { StatusBadge } from "./StatusBadge";
import { RecantDialog } from "./RecantDialog";
import { STATUS_EXPLAIN, TRUST_META, clockUtc } from "../lib/format";
import {
  closureOverBoard,
  useActiveBoard,
  useConsole,
  useDisplayStatuses,
} from "../state/useConsole";
import { Chip, Icon } from "./m3";

// The demo's incident is the one untrusted source; live boards may have one or
// none. Its taint closure over the active board decides which beliefs show the
// incident panel (fixtures carry inferred edges; a live board gains them once
// the recant materializes them).
const incidentSourceOf = (board: Board): Source | undefined =>
  board.sources.find((s) => s.trust === "untrusted");

// Plain-English details panel (beginner-first redesign). Answers, in order:
// what does this memory say, is it OK, where did it come from, where did it
// spread. Hashes/signatures/regions only appear with the Advanced toggle.
// The panel surface (rounded card, bg-surface, scroll) comes from AppShell.
export function Inspector() {
  const board = useActiveBoard();
  const selectedBelief = useConsole((s) => s.selectedBelief);
  const selectedSource = useConsole((s) => s.selectedSource);
  const statuses = useDisplayStatuses();

  const belief = selectedBelief ? board.beliefs.find((b) => b.id === selectedBelief) : null;

  return (
    <aside className="flex h-full flex-col">
      <header className="px-4 pb-2 pt-4">
        <h2 className="text-title-sm font-medium text-on-surface-variant">
          {belief ? "Memory details" : selectedSource ? "Source details" : "Details"}
        </h2>
      </header>

      <div className="flex-1">
        {belief ? (
          <BeliefInspector board={board} belief={belief} status={statuses[belief.id] ?? belief.status} />
        ) : selectedSource ? (
          <SourceInspector board={board} sourceId={selectedSource} />
        ) : (
          <Empty />
        )}
      </div>
    </aside>
  );
}

// A p-4 block with an M3 list-subheader, separated from the block above by an
// outline-variant rule.
function Section({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <section className="border-t border-outline-variant p-4">
      {label && <h3 className="mb-2 text-title-sm font-medium text-on-surface-variant">{label}</h3>}
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-label-md font-medium text-on-surface-variant">{label}</span>
      <span className="text-right text-body-sm text-on-surface">{children}</span>
    </div>
  );
}

// Custody-chain entry: M3 list row with a leading icon in a tonal circle.
function ChainRow({
  icon,
  title,
  detail,
}: {
  icon: string;
  title: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-container-high text-on-surface-variant">
        <Icon name={icon} size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-body-md text-on-surface">{title}</div>
        {detail && <div className="mt-0.5 text-body-sm text-on-surface-variant">{detail}</div>}
      </div>
    </li>
  );
}

function BeliefInspector({
  board,
  belief,
  status,
}: {
  board: Board;
  belief: Belief;
  status: Belief["status"];
}) {
  const advanced = useConsole((s) => s.advanced);
  const agentName = (id: string) => board.agents.find((a) => a.id === id)?.name ?? id;
  const beliefById = (id: string) => board.beliefs.find((b) => b.id === id);
  const src = belief.sourceId ? board.sources.find((s) => s.id === belief.sourceId) : null;
  const parents = board.derivations.filter((d) => d.childId === belief.id);
  const children = board.derivations.filter((d) => d.parentId === belief.id);
  const incidentSource = incidentSourceOf(board);
  const inIncident = incidentSource
    ? closureOverBoard(board, incidentSource.id).includes(belief.id)
    : false;

  return (
    <div>
      <div className="px-4 pb-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-label-md font-medium text-on-surface-variant">
            {agentName(belief.agentId)}, memory #{belief.seq}
          </span>
          <StatusBadge status={status} />
        </div>
        <p className="mt-2 text-body-lg text-on-surface">{belief.content}</p>
        <p className="mt-1.5 text-body-sm text-on-surface-variant">{STATUS_EXPLAIN[status]}</p>
      </div>

      <Section label="Where it came from">
        <ol className="flex flex-col gap-3">
          <ChainRow
            icon="database"
            title={src ? src.label : "Built from other memories"}
            detail={src ? `${TRUST_META[src.trust].label} source, ${src.uri}` : "see the memories it was based on below"}
          />
          <ChainRow
            icon="key"
            title={`Saved and signed by the ${agentName(belief.agentId)}`}
            detail={
              advanced ? (
                <HashChip hash={belief.sig.replace("\u2026", belief.hash.slice(8, 24))} label="ed25519" />
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
                  icon="account_tree"
                  title={`Based on: "${pb ? pb.content : p.parentId}"`}
                  detail={
                    p.kind === "inferred"
                      ? `reworded copy, found by meaning match (${Math.round(p.score * 100)}% similar)`
                      : "copied directly, with a link back"
                  }
                />
              );
            })
          ) : (
            <ChainRow icon="account_tree" title="This bot's first note on the topic" detail="not based on any earlier memory" />
          )}
        </ol>
      </Section>

      {children.length > 0 && (
        <Section label={`It spread to ${children.length} other ${children.length === 1 ? "memory" : "memories"}`}>
          <ul className="flex flex-col gap-2">
            {children.map((c) => {
              const cb = beliefById(c.childId);
              return (
                <li key={c.childId} className="rounded-md3-sm bg-surface-container-low px-3 py-2">
                  <div className="text-body-md text-on-surface">{cb?.content}</div>
                  <div className="mt-0.5 text-body-sm text-on-surface-variant">
                    {agentName(cb?.agentId ?? "")},{" "}
                    {c.kind === "inferred"
                      ? `reworded copy (${Math.round(c.score * 100)}% similar)`
                      : "copied directly"}
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {advanced && (
        <Section label="Technical record">
          <Field label="Hash">
            <HashChip hash={belief.hash} />
          </Field>
          <Field label="Prev">
            <HashChip hash={belief.prevHash} />
          </Field>
          <Field label="Created">
            <span className="mono text-body-sm">{clockUtc(belief.createdAt)} UTC</span>
          </Field>
          <Field label="Region">
            <span className="mono text-body-sm">{belief.region}</span>
          </Field>
        </Section>
      )}

      {inIncident && incidentSource && (
        <Section>
          <IncidentPanel source={incidentSource} />
        </Section>
      )}
    </div>
  );
}

function SourceInspector({ board, sourceId }: { board: Board; sourceId: string }) {
  const src = board.sources.find((s) => s.id === sourceId);
  const agentName = (id: string) => board.agents.find((a) => a.id === id)?.name ?? id;
  const own = board.beliefs.filter((b) => b.sourceId === sourceId);
  if (!src) return <Empty />;
  const isIncident = src.trust === "untrusted";

  return (
    <div>
      <div className="px-4 pb-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-label-md font-medium text-on-surface-variant">Source</span>
          <Chip label={TRUST_META[src.trust].label} />
        </div>
        <p className="mt-2 text-body-lg text-on-surface">{src.label}</p>
        <p className="mono mt-0.5 text-body-sm text-on-surface-variant">{src.uri}</p>
      </div>

      <Section label={`Memories that came from here (${own.length})`}>
        <ul className="flex flex-col gap-2">
          {own.map((b) => (
            <li key={b.id} className="rounded-md3-sm bg-surface-container-low px-3 py-2">
              <div className="text-body-md text-on-surface">{b.content}</div>
              <div className="mt-0.5 text-body-sm text-on-surface-variant">
                {agentName(b.agentId)}, memory #{b.seq}
              </div>
            </li>
          ))}
        </ul>
      </Section>

      {isIncident && (
        <Section>
          <IncidentPanel source={src} />
        </Section>
      )}
    </div>
  );
}

function IncidentPanel({ source }: { source: Source }) {
  const live = useConsole((s) => s.live);
  // Fixtures carry the scripted incident copy; a live untrusted source gets a
  // generic but accurate line. Either way the action is the same recant.
  const summary =
    !live && source.id === INCIDENT.sourceId
      ? INCIDENT.summary
      : "This source is untrusted. Recanting it takes back every memory that grew from it, across every bot, in one transaction.";
  const label = !live && source.id === INCIDENT.sourceId ? INCIDENT.id : source.label;
  return (
    <div className="rounded-md3-md bg-error-container p-3 text-on-error-container">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-label-lg font-medium">
          <Icon name="report" size={18} />
          Bad source alert
        </span>
        <span className="mono truncate text-label-sm">{label}</span>
      </div>
      <p className="mt-1.5 text-body-sm">{summary}</p>
      <RecantDialog sourceId={source.id} />
    </div>
  );
}

function Empty() {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center">
      <p className="text-body-md text-on-surface-variant">
        Click any memory card on the board, or a source on the left, to see its full story.
      </p>
    </div>
  );
}

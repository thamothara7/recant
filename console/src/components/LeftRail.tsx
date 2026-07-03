import { AGENTS, BELIEFS, SOURCES } from "../data/fixtures";
import type { AgentId, BeliefStatus, TrustTier } from "../data/types";
import { STATUS_META, TRUST_META } from "../lib/format";
import { useConsole } from "../state/useConsole";

// Worst status among an agent's beliefs decides its rail state.
const RANK: Record<BeliefStatus, number> = { active: 0, retracted: 1, suspect: 2, quarantined: 3 };

function agentState(agentId: AgentId, statuses: Record<string, BeliefStatus>): BeliefStatus {
  return BELIEFS.filter((b) => b.agentId === agentId).reduce<BeliefStatus>((worst, b) => {
    const s = statuses[b.id] ?? b.status;
    return RANK[s] > RANK[worst] ? s : worst;
  }, "active");
}

export function LeftRail() {
  const statuses = useConsole((s) => s.statuses);
  const selectedSource = useConsole((s) => s.selectedSource);
  const selectSource = useConsole((s) => s.selectSource);

  return (
    <aside className="flex w-[280px] shrink-0 flex-col overflow-y-auto border-r border-hairline bg-[var(--ink-2)]">
      <div className="px-4 pb-2 pt-4">
        <h2 className="label">Fleet</h2>
      </div>
      <div className="flex flex-col gap-1.5 px-3">
        {AGENTS.map((a) => {
          const st = agentState(a.id, statuses);
          const m = STATUS_META[st];
          const count = BELIEFS.filter((b) => b.agentId === a.id).length;
          return (
            <div
              key={a.id}
              className="rounded-panel border border-hairline bg-panel px-3 py-2.5"
              style={{ borderColor: st === "active" ? "var(--hairline)" : m.token }}
            >
              <div className="flex items-center justify-between">
                <span className="font-ui text-[13px] font-medium text-bond">{a.name}</span>
                <span
                  className="inline-flex items-center gap-1 mono text-[10px]"
                  style={{ color: m.token }}
                >
                  <span aria-hidden>{m.glyph}</span>
                  {st === "active" ? "clean" : m.label.toLowerCase()}
                </span>
              </div>
              <p className="mt-0.5 font-ui text-[11px] leading-tight text-bond-dim">{a.role}</p>
              <div className="mt-1.5 flex items-center justify-between mono text-[10px] text-bond-dim">
                <span>{a.region}</span>
                <span>
                  {count} beliefs · key {a.pubkey8}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="px-4 pb-2 pt-5">
        <h2 className="label">Sources</h2>
      </div>
      <div className="flex flex-col gap-1 px-3 pb-4">
        {SOURCES.map((src) => {
          const on = selectedSource === src.id;
          return (
            <button
              key={src.id}
              onClick={() => selectSource(on ? null : src.id)}
              className="rounded-panel border px-3 py-2 text-left transition-colors"
              style={{
                borderColor: on ? "var(--uv)" : "var(--hairline)",
                background: on ? "color-mix(in srgb, var(--uv) 8%, var(--panel))" : "var(--panel)",
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-ui text-[12.5px] text-bond">{src.label}</span>
                <TrustChip trust={src.trust} />
              </div>
              <p className="mt-0.5 truncate mono text-[10px] text-bond-dim">{src.uri}</p>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function TrustChip({ trust }: { trust: TrustTier }) {
  const m = TRUST_META[trust];
  return (
    <span
      className="rounded-tag px-1.5 py-[1px] mono text-[9px] uppercase tracking-wider"
      style={{
        color: m.token,
        border: `1px solid color-mix(in srgb, ${m.token} 45%, transparent)`,
        background: `color-mix(in srgb, ${m.token} 10%, transparent)`,
      }}
    >
      {m.label}
    </span>
  );
}

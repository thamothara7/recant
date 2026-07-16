import type { Belief, BeliefStatus, TrustTier } from "../data/types";
import { STATUS_META, TRUST_META } from "../lib/format";
import { useActiveBoard, useConsole, useDisplayStatuses } from "../state/useConsole";
import { Chip, Icon } from "./m3";

// Worst status among a bot's memories decides its rail state.
const RANK: Record<BeliefStatus, number> = { active: 0, retracted: 1, suspect: 2, quarantined: 3 };

function agentState(
  agentId: string,
  beliefs: Belief[],
  statuses: Record<string, BeliefStatus>,
): BeliefStatus {
  return beliefs.filter((b) => b.agentId === agentId).reduce<BeliefStatus>((worst, b) => {
    const s = statuses[b.id] ?? b.status;
    return RANK[s] > RANK[worst] ? s : worst;
  }, "active");
}

const TRUST_ICON: Record<TrustTier, string> = {
  verified: "verified",
  partner: "handshake",
  public: "public",
  untrusted: "gpp_bad",
};

export function LeftRail() {
  const statuses = useDisplayStatuses();
  const board = useActiveBoard();
  const advanced = useConsole((s) => s.advanced);
  const selectedSource = useConsole((s) => s.selectedSource);
  const selectSource = useConsole((s) => s.selectSource);

  return (
    <aside className="flex w-[280px] shrink-0 flex-col overflow-y-auto">
      <h2 className="px-4 pb-2 pt-4 text-title-sm font-medium text-on-surface-variant">Your bots</h2>
      <div className="flex flex-col">
        {board.agents.map((a) => {
          const st = agentState(a.id, board.beliefs, statuses);
          const m = STATUS_META[st];
          return (
            <div key={a.id} className="flex h-14 w-full items-center gap-3 rounded-full px-4 text-left text-on-surface">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary-container text-on-primary-container">
                <Icon name="smart_toy" size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-label-lg font-medium">{a.name}</span>
                {/* Region only: a truncated key fragment conveys nothing; the
                    full pubkey lives in the inspector's technical record. */}
                {advanced ? (
                  <span className="mono block truncate text-body-sm text-on-surface-variant">
                    {a.region}
                  </span>
                ) : (
                  <span className="block truncate text-body-sm text-on-surface-variant">
                    {a.role || a.region}
                  </span>
                )}
              </span>
              <Chip
                icon={m.icon}
                label={st === "active" ? "all clear" : m.label.toLowerCase()}
                container={m.container}
                onContainer={m.onContainer}
              />
            </div>
          );
        })}
      </div>

      <h2 className="px-4 pb-2 pt-5 text-title-sm font-medium text-on-surface-variant">Where facts come from</h2>
      <p className="px-4 pb-2 text-body-sm text-on-surface-variant">
        Click a source to see every memory that grew from it.
      </p>
      <div className="flex flex-col pb-4">
        {board.sources.map((src) => {
          const on = selectedSource === src.id;
          return (
            <button
              key={src.id}
              onClick={() => selectSource(on ? null : src.id)}
              className={`state-layer flex min-h-14 w-full items-center gap-3 rounded-md3-lg px-4 py-2 text-left ${
                on ? "bg-secondary-container text-on-secondary-container" : "text-on-surface"
              }`}
            >
              <Icon
                name={TRUST_ICON[src.trust]}
                size={20}
                className="shrink-0"
                style={{ color: TRUST_META[src.trust].color }}
              />
              <span className="min-w-0 flex-1">
                {/* Source names are the demo's vocabulary: wrap, never truncate.
                    Only the URI truncates. */}
                <span className="block text-label-lg">{src.label}</span>
                <span className="mono block truncate text-body-sm text-on-surface-variant">{src.uri}</span>
              </span>
              <Chip label={TRUST_META[src.trust].label} />
            </button>
          );
        })}
      </div>
    </aside>
  );
}

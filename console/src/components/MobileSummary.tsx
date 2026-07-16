import { AGENTS, BELIEFS, SOURCES } from "../data/fixtures";
import { STATUS_META } from "../lib/format";
import { LogoMark } from "./LogoMark";
import { Chip, Icon } from "./m3";

// Small screens get the read-only incident summary, never the board (skill 4:
// "Do not attempt the board on small screens"). One scrolling column: what
// happened, the three bad memories, what Recant did about it.
const agentName = (id: string) => AGENTS.find((a) => a.id === id)?.name ?? id;
const sourceLabel = (id: string | null) =>
  id ? (SOURCES.find((s) => s.id === id)?.label ?? id) : "built from other memories";

export function MobileSummary() {
  const wrong = BELIEFS.filter((b) => b.status === "suspect");
  const meta = STATUS_META.suspect;

  return (
    <div className="mx-auto flex min-h-full max-w-md flex-col gap-4 p-4">
      <header className="flex items-center gap-3 pt-2">
        <LogoMark />
        <span className="text-title-lg text-on-surface">Recant</span>
      </header>

      <section className="rounded-md3-lg bg-surface p-4">
        <h1 className="text-title-lg text-on-surface">
          One bad web post poisoned {new Set(wrong.map((b) => b.agentId)).size} bots
        </h1>
        <p className="mt-2 text-body-md text-on-surface-variant">
          Research bot saved a fake fact from a random forum post. Two other
          bots built on it, reworded, with no links back to the original.
          Recant found every copy and took them all back in one database
          transaction, with proof.
        </p>
      </section>

      <section className="rounded-md3-lg bg-surface p-4">
        <h2 className="text-title-sm font-medium text-on-surface-variant">
          The bad memories
        </h2>
        <ul className="mt-3 flex flex-col gap-3">
          {wrong.map((b) => (
            <li
              key={b.id}
              className="rounded-md3-md border border-outline-variant bg-surface-container-lowest p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-label-lg font-medium text-on-surface">
                  {agentName(b.agentId)}
                </span>
                <Chip
                  icon={meta.icon}
                  label={meta.label}
                  container={meta.container}
                  onContainer={meta.onContainer}
                />
              </div>
              <p className="mt-1.5 text-body-md text-on-surface">{b.content}</p>
              <p className="mt-1 text-body-sm text-on-surface-variant">
                from: {sourceLabel(b.sourceId)}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex items-start gap-3 rounded-md3-lg bg-secondary-container p-4 text-on-secondary-container">
        <Icon name="desktop_windows" size={20} />
        <p className="text-body-md">
          This is the read-only summary. Open Recant on a laptop for the live
          memory board: watch the bad fact spread, take it back with one click,
          and rewind time to prove it.
        </p>
      </section>
    </div>
  );
}

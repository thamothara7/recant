import { useEffect, useMemo, useRef, useState } from "react";
import { dismissExploreHint } from "../lib/exploreHint";
import { STATUS_META } from "../lib/format";
import { useActiveBoard, useConsole, useDisplayStatuses } from "../state/useConsole";
import { Chip, Icon, IconButton } from "./m3";

export function MemorySearch() {
  const board = useActiveBoard();
  const statuses = useDisplayStatuses();
  const selectBelief = useConsole((s) => s.selectBelief);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return [];

    return board.beliefs
      .filter((belief) => {
        const agent = board.agents.find((item) => item.id === belief.agentId)?.name ?? "";
        const source = board.sources.find((item) => item.id === belief.sourceId)?.label ?? "";
        const status = STATUS_META[statuses[belief.id] ?? belief.status].label;
        return [belief.content, agent, source, status, belief.id]
          .join(" ")
          .toLocaleLowerCase()
          .includes(needle);
      })
      .slice(0, 6);
  }, [board, query, statuses]);

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.key !== "/" ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable
      ) {
        return;
      }
      event.preventDefault();
      inputRef.current?.focus();
      setOpen(true);
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  const choose = (id: string) => {
    selectBelief(id);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  };

  const showResults = open && query.trim().length > 0;

  return (
    <div className="relative">
      <div className="flex h-10 w-[300px] items-center gap-2 rounded-full bg-surface-container-high px-3 text-on-surface-variant focus-within:ring-2 focus-within:ring-primary">
        <Icon name="search" size={20} />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            dismissExploreHint();
          }}
          onBlur={(event) => {
            if (!event.currentTarget.parentElement?.parentElement?.contains(event.relatedTarget)) {
              setOpen(false);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setQuery("");
              setOpen(false);
              event.currentTarget.blur();
            } else if (event.key === "Enter" && results[0]) {
              event.preventDefault();
              choose(results[0].id);
            }
          }}
          role="combobox"
          aria-label="Search memories"
          aria-expanded={showResults}
          aria-controls="memory-search-results"
          aria-autocomplete="list"
          placeholder="Search memories"
          className="min-w-0 flex-1 bg-transparent text-body-md text-on-surface outline-none placeholder:text-on-surface-variant focus-visible:outline-none"
        />
        {query ? (
          <IconButton
            icon="close"
            label="Clear search"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              setQuery("");
              inputRef.current?.focus();
            }}
            className="!h-8 !w-8"
          />
        ) : (
          <span className="mono rounded-md3-xs border border-outline-variant px-1.5 text-label-sm">/</span>
        )}
      </div>

      {showResults && (
        <div
          id="memory-search-results"
          role="listbox"
          className="absolute right-0 top-12 z-50 w-[380px] overflow-hidden rounded-md3-lg bg-surface-container-high shadow-elevation-2"
        >
          {results.length > 0 ? (
            <div className="py-2">
              {results.map((belief) => {
                const agent =
                  board.agents.find((item) => item.id === belief.agentId)?.name ?? belief.agentId;
                const meta = STATUS_META[statuses[belief.id] ?? belief.status];
                return (
                  <button
                    key={belief.id}
                    role="option"
                    aria-selected={false}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(belief.id)}
                    className="state-layer flex w-full items-center gap-3 px-4 py-3 text-left text-on-surface"
                  >
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary-container text-on-primary-container">
                      <Icon name="smart_toy" size={18} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-label-lg font-medium">{agent}</span>
                      <span className="block truncate text-body-sm text-on-surface-variant">
                        {belief.content}
                      </span>
                    </span>
                    <Chip
                      icon={meta.icon}
                      label={meta.label}
                      container={meta.container}
                      onContainer={meta.onContainer}
                    />
                  </button>
                );
              })}
              {results.length === 6 && (
                <p className="px-4 pb-1 pt-2 text-body-sm text-on-surface-variant">
                  Refine the search to narrow the results.
                </p>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-3 px-4 py-5 text-on-surface-variant">
              <Icon name="search_off" size={20} />
              <p className="text-body-md">No memories match “{query.trim()}”.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

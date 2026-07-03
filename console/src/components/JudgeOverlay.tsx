import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { PrimitiveKind } from "../data/types";
import { useConsole } from "../state/useConsole";

// The judging criterion "which CockroachDB primitives did you use" rendered live.
// Chips flash on X-Recant-Primitive responses; the log keeps the SQL peek.
const KIND_TOKEN: Record<PrimitiveKind, string> = {
  "SERIALIZABLE TXN": "var(--attested)",
  "VECTOR kNN": "var(--uv)",
  CHANGEFEED: "var(--suspect)",
  AOST: "var(--uv)",
  "ROW TTL": "var(--bond-dim)",
  "MCP TOOL": "var(--attested)",
};

export function JudgeOverlay() {
  const overlayOn = useConsole((s) => s.overlayOn);
  const primitives = useConsole((s) => s.primitives);
  const log = useConsole((s) => s.primitiveLog);
  const [openLog, setOpenLog] = useState(false);
  const reduce = useReducedMotion();

  if (!overlayOn) return null;

  return (
    <div className="pointer-events-none fixed right-4 top-14 z-30 flex w-[300px] flex-col items-end gap-2">
      <AnimatePresence>
        {primitives.map((p) => (
          <motion.div
            key={p.id}
            initial={reduce ? false : { opacity: 0, x: 16, scale: 0.98 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, x: 16 }}
            transition={{ duration: reduce ? 0 : 0.18 }}
            className="pointer-events-auto w-full rounded-tag border bg-[color-mix(in_srgb,var(--panel)_92%,black)] px-3 py-2 shadow-lift backdrop-blur-sm"
            style={{ borderColor: `color-mix(in srgb, ${KIND_TOKEN[p.kind]} 55%, transparent)` }}
          >
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: KIND_TOKEN[p.kind] }} />
              <span className="mono text-[11px] font-medium tracking-wide" style={{ color: KIND_TOKEN[p.kind] }}>
                {p.kind}
              </span>
              <span className="ml-auto mono text-[10px] text-bond-dim">{p.detail}</span>
            </div>
            <div className="mt-1 truncate mono text-[9.5px] text-bond-dim/80">{p.sql}</div>
          </motion.div>
        ))}
      </AnimatePresence>

      {log.length > 0 && (
        <div className="pointer-events-auto w-full">
          <button
            onClick={() => setOpenLog((v) => !v)}
            className="ml-auto flex items-center gap-1.5 rounded-tag border border-hairline bg-panel px-2 py-1 mono text-[10px] text-bond-dim hover:text-bond"
          >
            <span>primitive log</span>
            <span className="text-uv">{log.length}</span>
            <span aria-hidden>{openLog ? "▾" : "▸"}</span>
          </button>
          {openLog && (
            <div className="mt-1 max-h-[280px] w-full overflow-y-auto rounded-panel border border-hairline bg-[var(--ink-2)] p-2">
              {log.map((p) => (
                <div key={p.id} className="border-b border-hairline/60 py-1.5 last:border-0">
                  <div className="flex items-center gap-2">
                    <span className="mono text-[10px]" style={{ color: KIND_TOKEN[p.kind] }}>
                      {p.kind}
                    </span>
                    <span className="ml-auto mono text-[9px] text-bond-dim">{p.detail}</span>
                  </div>
                  <div className="mono text-[9px] leading-tight text-bond-dim/80">{p.sql}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

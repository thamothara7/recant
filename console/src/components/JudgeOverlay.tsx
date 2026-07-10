import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useConsole } from "../state/useConsole";
import { Button } from "./m3";

// The judging criterion "which CockroachDB primitives did you use" rendered
// live. Chips flash on X-Recant-Primitive responses as M3 snackbars, docked
// bottom-leading OVER THE BOARD (rendered inside the board card by AppShell)
// so they never occlude the rail or the inspector; the slide-out log keeps the
// SQL peek and opens upward from its toggle.
export function JudgeOverlay() {
  const overlayOn = useConsole((s) => s.overlayOn);
  const primitives = useConsole((s) => s.primitives);
  const log = useConsole((s) => s.primitiveLog);
  const [openLog, setOpenLog] = useState(false);
  const reduce = useReducedMotion();

  if (!overlayOn) return null;

  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-30 flex w-[300px] flex-col items-start gap-2">
      <AnimatePresence>
        {primitives.map((p) => (
          <motion.div
            key={p.id}
            initial={reduce ? false : { opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 8 }}
            transition={{ duration: reduce ? 0 : 0.18 }}
            className="pointer-events-auto flex w-full flex-col gap-0.5 rounded-md3-sm bg-inverse-surface px-4 py-3 text-inverse-on-surface shadow-elevation-3"
          >
            <span className="text-label-lg font-medium">{p.kind}</span>
            <span className="mono truncate text-label-md opacity-90">{p.detail}</span>
          </motion.div>
        ))}
      </AnimatePresence>

      {log.length > 0 && (
        <div className="pointer-events-auto relative flex w-full flex-col items-start">
          {openLog && (
            <div className="absolute bottom-full mb-1 max-h-[280px] w-full overflow-y-auto rounded-md3-lg border border-outline-variant bg-surface p-2 shadow-elevation-2">
              {log.map((p) => (
                <div key={p.id} className="border-b border-outline-variant py-2 last:border-0">
                  <div className="flex items-center gap-2">
                    <span className="text-label-md font-medium text-on-surface">{p.kind}</span>
                    <span className="mono ml-auto text-label-sm text-on-surface-variant">{p.detail}</span>
                  </div>
                  <div className="mono mt-1 rounded-md3-xs bg-surface-container-low p-2 text-body-sm text-on-surface-variant">
                    {p.sql}
                  </div>
                </div>
              ))}
            </div>
          )}
          <Button
            variant="text"
            icon={openLog ? "expand_more" : "expand_less"}
            onClick={() => setOpenLog((v) => !v)}
          >
            primitive log
            <span className="mono">{log.length}</span>
          </Button>
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { useConsole } from "../state/useConsole";
import { Icon } from "./m3";

// Cluster health + a live forensics-query counter. Killing a node flips it to
// down, but the counter keeps climbing, the visual argument for survivability
// (skill 4, proof moment 6).
export function ClusterBar() {
  const cluster = useConsole((s) => s.cluster);
  const killNode = useConsole((s) => s.killNode);
  const reviveNode = useConsole((s) => s.reviveNode);
  const [queries, setQueries] = useState(48213);

  const upCount = cluster.filter((n) => n.up).length;
  const regions = new Set(cluster.map((n) => n.region.slice(0, -1))).size;

  useEffect(() => {
    // Only the surviving nodes serve, but the cluster keeps answering.
    const t = window.setInterval(() => setQueries((q) => q + upCount), 650);
    return () => window.clearInterval(t);
  }, [upCount]);

  return (
    <div className="flex items-center gap-4">
      <div className="flex items-center gap-2">
        <span className="whitespace-nowrap text-label-md font-medium text-on-surface-variant">Servers</span>
        <span className="whitespace-nowrap text-body-sm text-on-surface-variant">
          {upCount}/{cluster.length} healthy · {regions} regions
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        {cluster.map((n) => (
          <span
            key={n.id}
            className="flex h-7 items-center gap-1.5 rounded-md3-sm border border-outline-variant px-2"
          >
            <Icon
              name="dns"
              size={14}
              style={{ color: n.up ? "var(--md-success)" : "var(--md-error)" }}
            />
            <span className="text-label-sm font-medium text-on-surface-variant">{n.up ? "up" : "down"}</span>
            <span className="mono text-label-sm text-on-surface-variant">{n.region}</span>
            <button
              title={n.up ? `${n.region} · click to kill` : `${n.region} · click to revive`}
              aria-label={`${n.region} node, ${n.up ? "up, activate to kill" : "down, activate to revive"}`}
              onClick={() => (n.up ? killNode(n.id) : reviveNode(n.id))}
              className="state-layer -mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-on-surface-variant"
            >
              <Icon name="power_settings_new" size={14} />
            </button>
          </span>
        ))}
      </div>

      <div className="flex items-center gap-1.5 whitespace-nowrap">
        <span className="mono text-label-md tabular-nums text-on-surface">{queries.toLocaleString()}</span>
        <span className="text-label-sm font-medium text-on-surface-variant">forensics queries</span>
      </div>
    </div>
  );
}

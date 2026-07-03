import { useEffect, useState } from "react";
import { useConsole } from "../state/useConsole";

// Cluster health + a live forensics-query counter. Killing a node flips it to ⛔
// but the counter keeps climbing, the visual argument for survivability (skill 4,
// proof moment 6).
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
    <div className="flex items-center gap-4 px-4">
      <div className="flex items-center gap-2">
        <span className="label whitespace-nowrap">Servers</span>
        <span className="mono text-[10px] text-bond-dim">
          {upCount}/{cluster.length} healthy · {regions} regions
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        {cluster.map((n) => (
          <button
            key={n.id}
            title={n.up ? `${n.region} · click to kill` : `${n.region} · click to revive`}
            aria-label={`${n.region} node, ${n.up ? "up, activate to kill" : "down, activate to revive"}`}
            onClick={() => (n.up ? killNode(n.id) : reviveNode(n.id))}
            className="flex items-center gap-1 rounded-tag border px-1.5 py-1 mono text-[9px] transition-colors"
            style={{
              borderColor: n.up ? "color-mix(in srgb, var(--attested) 40%, transparent)" : "var(--quarantined)",
              color: n.up ? "var(--attested)" : "var(--quarantined)",
              background: n.up ? "transparent" : "color-mix(in srgb, var(--quarantined) 12%, transparent)",
            }}
          >
            <span aria-hidden>{n.up ? "●" : "⛔"}</span>
            {n.region}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1.5 whitespace-nowrap">
        <span className="mono text-[13px] tabular-nums text-bond">{queries.toLocaleString()}</span>
        <span className="label !text-[9px]">forensics queries</span>
      </div>
    </div>
  );
}

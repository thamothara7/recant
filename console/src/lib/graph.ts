import * as Dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";
import type { Belief, Derivation } from "../data/types";

export const NODE_W = 244;
export const NODE_H = 114;

export interface BeliefNodeData extends Record<string, unknown> {
  belief: Belief;
}

// Deterministic left-to-right layered layout. Dagre is a pure function of the
// input, so positions are reproducible frame-for-frame (skill 4); nodes are not
// draggable, so they never drift. Takes the board explicitly so the same layout
// serves fixtures and live seed data.
export function layout(
  beliefs: Belief[],
  derivations: Derivation[],
): { nodes: Node<BeliefNodeData>[]; edges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", ranksep: 96, nodesep: 26, marginx: 24, marginy: 24 });

  const ids = new Set(beliefs.map((b) => b.id));
  for (const b of beliefs) g.setNode(b.id, { width: NODE_W, height: NODE_H });
  // Only edges whose endpoints are both on the board (a live derivation could
  // reference a belief outside this snapshot); dagre throws on dangling edges.
  const edgeList = derivations.filter((d) => ids.has(d.parentId) && ids.has(d.childId));
  for (const d of edgeList) g.setEdge(d.parentId, d.childId);
  Dagre.layout(g);

  const nodes: Node<BeliefNodeData>[] = beliefs.map((belief) => {
    const { x, y } = g.node(belief.id);
    return {
      id: belief.id,
      type: "belief",
      position: { x: x - NODE_W / 2, y: y - NODE_H / 2 },
      data: { belief },
      draggable: false,
      connectable: false,
      selectable: true,
    };
  });

  const edges: Edge[] = edgeList.map((d) => ({
    id: `${d.parentId}->${d.childId}`,
    source: d.parentId,
    target: d.childId,
    className: d.kind === "inferred" ? "rf-edge-inferred" : "rf-edge-explicit",
    data: { kind: d.kind, score: d.score },
    animated: false,
    type: "default",
  }));

  return { nodes, edges };
}

// The custody thread of a belief: every derivation edge on its provenance chain,
// walking ancestors (where it came from) and descendants (where it spread).
export function custodyEdgeIds(
  selectedId: string | null,
  derivations: Derivation[],
): Set<string> {
  const out = new Set<string>();
  if (!selectedId) return out;

  // visited guards keep the walk finite even if the derivation graph ever cycles.
  const upSeen = new Set([selectedId]);
  const up = [selectedId];
  while (up.length) {
    const cur = up.pop()!;
    for (const d of derivations)
      if (d.childId === cur) {
        out.add(`${d.parentId}->${d.childId}`);
        if (!upSeen.has(d.parentId)) {
          upSeen.add(d.parentId);
          up.push(d.parentId);
        }
      }
  }
  const downSeen = new Set([selectedId]);
  const down = [selectedId];
  while (down.length) {
    const cur = down.pop()!;
    for (const d of derivations)
      if (d.parentId === cur) {
        out.add(`${d.parentId}->${d.childId}`);
        if (!downSeen.has(d.childId)) {
          downSeen.add(d.childId);
          down.push(d.childId);
        }
      }
  }
  return out;
}

// src/layouts/flow.ts - directional DAG layouts (beyond the default packing).
//
//   flow-down / flow-right : ELK `layered` flow network — ranks nodes by the
//     directed step-flow wires and orders within layers to cut crossings, so
//     store -> process -> store dependencies line up. 'hierarchy' orients it
//     top-to-bottom, 'flow' left-to-right. HUB-store wires (bulk/listeners/…
//     wired by ~everything) are excluded so the graph stays sparse; with that +
//     low thoroughness it is fast (the un-pruned version jammed ~30s on
//     hub-heavy composites).

import ELK from 'elkjs/lib/elk.bundled.js';
import type { Node, Edge } from '@xyflow/react';
import { TIERS } from './tiers';
import { wireStoreEndpoint, hubStoreIds } from '../storeFacts';
import { fullFootprint, removeOverlaps, type Box } from './clusterGrid';
import type { LayoutMode, LayoutResult } from './types';

const elk = new ELK();

// ---- ELK layered flow network -------------------------------------------------

async function elkFlowLayout(
  nodes: Node[], edges: Edge[], direction: 'DOWN' | 'RIGHT' = 'RIGHT',
): Promise<LayoutResult> {
  if (nodes.length === 0) return { nodes };

  const footprint = new Map(nodes.map((n) => [n.id, fullFootprint(n)] as const));
  const nodeIds = new Set(nodes.map((n) => n.id));

  // Hub-store wires (bulk/listeners wired by ~everything) only jam ELK ~30s on
  // LARGE composites — exclude them there for speed. On normal composites keep
  // EVERY store wire so each store sits between the processes that read/write it
  // (node → process → node), instead of floating free (which scattered the
  // graph). Threshold picked well above ordinary composites, below v2ecoli-scale.
  const nProcs = nodes.filter((n) => n.type === 'process').length;
  const hubs = nProcs > 24 ? hubStoreIds(edges) : new Set<string>();
  const flowEdges: Array<{ source: string; target: string }> = [];
  const seen = new Set<string>();
  const push = (a: string, b: string) => {
    if (!nodeIds.has(a) || !nodeIds.has(b) || a === b) return;
    const k = a + ' ' + b;
    if (seen.has(k)) return;
    seen.add(k);
    flowEdges.push({ source: a, target: b });
  };
  for (const e of edges) {
    const kind = (e.data as { edgeType?: string } | undefined)?.edgeType;
    if (kind === 'place') { push(e.source, e.target); continue; }   // place graph
    const store = wireStoreEndpoint(e);
    if (store == null || hubs.has(store)) continue;                 // hub wire → skip
    push(e.source, e.target);                                       // step flow
  }

  const elkGraph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': direction,
      // Tighter layers: nodes reserve their FULL-tier footprint (so nothing
      // overlaps when zoomed in), which already spaces layers generously — a
      // large between-layer gap on top of that leaves sinks stranded far away
      // at low zoom. Keep the gap small; the footprints still prevent overlap.
      'elk.layered.spacing.nodeNodeBetweenLayers': '48',
      'elk.spacing.nodeNode': '36',
      // Speed on the sparse (hub-free) graph.
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
      'elk.layered.nodePlacement.strategy': 'SIMPLE',
      'elk.layered.thoroughness': '1',
    } as Record<string, string>,
    children: nodes.map((n) => {
      const f = footprint.get(n.id)!;
      return { id: n.id, width: f.w, height: f.h };
    }),
    edges: flowEdges.map((s, i) => ({ id: `f${i}`, sources: [s.source], targets: [s.target] })),
  };

  const res = (await elk.layout(elkGraph as never)) as {
    children?: Array<{ id: string; x?: number; y?: number }>;
  };
  const pos = new Map<string, { x: number; y: number }>();
  for (const c of res.children ?? []) pos.set(c.id, { x: c.x ?? 0, y: c.y ?? 0 });
  const out = nodes.map((n) => {
    const p = pos.get(n.id);
    return p ? { ...n, position: { x: p.x, y: p.y } } : n;
  });

  // flow-right: the STEP flow runs left→right (ELK above), but store CONTAINMENT
  // should still read top→bottom — a parent store sits above its children
  // (tissue above fields/cells, cells above cell). ELK can only rank one
  // direction per pass, so we post-process: re-bank each store onto a
  // horizontal level by its place-graph depth, keeping its ELK flow x.
  // Processes keep their ELK positions (the horizontal flow). Store rows are
  // spaced by the tallest store so deeper levels never overlap the level above.
  if (direction === 'RIGHT') {
    const storeNodes = out.filter((n) => n.type === 'store');
    if (storeNodes.length > 0) {
      const depthOf = (n: Node): number => {
        const p = (n.data as { path?: unknown } | undefined)?.path;
        return Array.isArray(p) && p.length > 0 ? p.length : 1;
      };
      const rowH = Math.max(
        90,
        ...storeNodes.map((n) => footprint.get(n.id)?.h ?? 0),
      ) + 70;                                   // tallest store + inter-row gap
      const baseY = Math.min(...out.map((n) => n.position.y));
      for (const n of storeNodes) {
        n.position = { x: n.position.x, y: baseY + (depthOf(n) - 1) * rowH };
      }
    }
  }

  // Guarantee no overlaps. ELK reserves each node's footprint, but the RIGHT
  // re-banking above can slide a store onto a process, and tight layer spacing
  // can graze neighbours — push any overlapping boxes apart (order-stable,
  // minimal move; early-returns when nothing overlaps, e.g. clean flow-down).
  const boxes: Box[] = out.map((n) => {
    const f = footprint.get(n.id) ?? { w: 120, h: 80 };
    return { id: n.id, x: n.position.x, y: n.position.y, w: f.w, h: f.h };
  });
  removeOverlaps(boxes, 28, 1000);
  const boxById = new Map(boxes.map((b) => [b.id, b] as const));
  return {
    nodes: out.map((n) => {
      const b = boxById.get(n.id);
      return b ? { ...n, position: { x: b.x, y: b.y } } : n;
    }),
  };
}

// "Hierarchy": ELK layered top-to-bottom — the store dependency hierarchy.
export const flowElkDownMode: LayoutMode = {
  id: 'flow-down', label: 'hierarchy', tiers: TIERS,
  run: (nodes, edges) => elkFlowLayout(nodes, edges, 'DOWN'),
};

// "Flow": ELK layered left-to-right — the workflow DAG, so store -> process ->
// store dependencies line up in reading order.
export const flowElkRightMode: LayoutMode = {
  id: 'flow-right', label: 'flow', tiers: TIERS,
  run: (nodes, edges) => elkFlowLayout(nodes, edges, 'RIGHT'),
};

// src/layouts/flow.ts - directional layouts beyond the default relationship packing.
//
//   flow-tb / flow-lr : the fast "Stack stores by depth" arrangement
//     (depthStackLayout) oriented top-to-bottom / left-to-right. Pure + instant.
//   flow-elk          : ELK `layered` flow network - ranks nodes by the directed
//     step-flow wires, orders within layers to cut crossings. HUB-store wires
//     (bulk/listeners/... wired by ~everything) are excluded so the graph stays
//     sparse; with that + low thoroughness it is fast (the un-pruned version
//     jammed the browser ~30s on hub-heavy composites).

import ELK from 'elkjs/lib/elk.bundled.js';
import type { Node, Edge } from '@xyflow/react';
import { TIERS } from './tiers';
import { depthStackLayout } from './depthStack';
import { wireStoreEndpoint, hubStoreIds } from '../storeFacts';
import { fullFootprint } from './clusterGrid';
import type { LayoutMode, LayoutResult } from './types';

const elk = new ELK();

// ---- fast stack layouts (down / right) ----------------------------------------

function stackLayout(nodes: Node[], edges: Edge[], direction: 'DOWN' | 'RIGHT'): LayoutResult {
  if (nodes.length === 0) return { nodes };
  const res = depthStackLayout(nodes, edges);
  if (direction === 'DOWN') return res;
  return {
    nodes: res.nodes.map((n) => (n.position ? { ...n, position: { x: n.position.y, y: n.position.x } } : n)),
    bands: res.bands,
  };
}

export const flowDownMode: LayoutMode = {
  id: 'flow-tb', label: 'Stack - top to bottom', tiers: TIERS,
  run: (nodes, edges) => Promise.resolve(stackLayout(nodes, edges, 'DOWN')),
};

export const flowRightMode: LayoutMode = {
  id: 'flow-lr', label: 'Stack - left to right', tiers: TIERS,
  run: (nodes, edges) => Promise.resolve(stackLayout(nodes, edges, 'RIGHT')),
};

// ---- ELK layered flow network -------------------------------------------------

async function elkFlowLayout(nodes: Node[], edges: Edge[]): Promise<LayoutResult> {
  if (nodes.length === 0) return { nodes };

  const footprint = new Map(nodes.map((n) => [n.id, fullFootprint(n)] as const));
  const nodeIds = new Set(nodes.map((n) => n.id));

  const hubs = hubStoreIds(edges);
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
      'elk.direction': 'RIGHT',
      'elk.layered.spacing.nodeNodeBetweenLayers': '90',
      'elk.spacing.nodeNode': '44',
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
  return { nodes: out };
}

export const flowElkMode: LayoutMode = {
  id: 'flow-elk', label: 'Flow network (ELK)', tiers: TIERS,
  run: (nodes, edges) => elkFlowLayout(nodes, edges),
};

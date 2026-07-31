// src/layouts/flow.ts - directional FLOW layouts (top-to-bottom / left-to-right).
//
// Runs ELK's `layered` algorithm, which ranks nodes into layers by following
// the directed wire graph (a store a process WRITES feeds the store a
// downstream process READS), then orders within each layer to minimise
// crossings. `elk.direction` sets the flow axis: DOWN (top-to-bottom) or RIGHT
// (left-to-right). This is the "order by the flow network" view; the default
// `hierarchy` (clusterGrid) mode is the non-directional relationship packing.

import ELK from 'elkjs/lib/elk.bundled.js';
import type { Node, Edge } from '@xyflow/react';
import { TIERS } from './tiers';
import { wireStoreEndpoint } from '../storeFacts';
import { fullFootprint } from './clusterGrid';
import type { LayoutMode, LayoutResult } from './types';

const elk = new ELK();

async function flowLayout(
  nodes: Node[], edges: Edge[], direction: 'DOWN' | 'RIGHT',
): Promise<LayoutResult> {
  if (nodes.length === 0) return { nodes };

  const footprint = new Map(nodes.map((n) => [n.id, fullFootprint(n)] as const));
  const nodeIds = new Set(nodes.map((n) => n.id));

  // Directed flow edges = the wires (process/store); place/structural edges are
  // excluded from ranking. Deduped on (source -> target).
  const flowEdges: Array<{ source: string; target: string }> = [];
  const seen = new Set<string>();
  for (const e of edges) {
    if (wireStoreEndpoint(e) == null) continue;
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
    const k = e.source + ' ' + e.target;
    if (seen.has(k)) continue;
    seen.add(k);
    flowEdges.push({ source: e.source, target: e.target });
  }

  const elkGraph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': direction,
      'elk.layered.spacing.nodeNodeBetweenLayers': '90',
      'elk.spacing.nodeNode': '44',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
      'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
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

export const flowDownMode: LayoutMode = {
  id: 'flow-tb',
  label: 'Flow - top to bottom',
  tiers: TIERS,
  run: (nodes, edges) => flowLayout(nodes, edges, 'DOWN'),
};

export const flowRightMode: LayoutMode = {
  id: 'flow-lr',
  label: 'Flow - left to right',
  tiers: TIERS,
  run: (nodes, edges) => flowLayout(nodes, edges, 'RIGHT'),
};

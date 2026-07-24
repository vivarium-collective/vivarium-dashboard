// src/layouts/depthStack.ts — "stack stores by depth" global arrangement.
//
// A structural alternative to the force overview: stores are banded by their
// nesting depth (top-level stores in the top band, their children below, and
// so on), and each process is seeded beneath the stores it wires, then the
// shared overlap-removal pass guarantees nothing collides. This makes the
// store HIERARCHY legible — "outers above, inners below" — where the force
// layout optimizes for wire length instead.
//
// Pure: no React, no DOM. Returns React-Flow node TOP-LEFT positions.

import type { Node, Edge } from '@xyflow/react';
import { fullFootprint, removeOverlaps, type Box } from './clusterGrid';
import type { LayoutResult } from './types';

/** Horizontal gap between cards within a band. */
const H_GAP = 40;
/** Vertical gap between successive depth bands. */
const BAND_V_GAP = 90;
/** Gap between the deepest store band and the process band below it. */
const PROC_GAP = 120;
/** Clearance enforced by the overlap-removal pass. */
const MARGIN = 36;

/** Depth of a node from its bigraph path length (root = 1). Missing path → 1. */
function depthOf(n: Node): number {
  const path = (n.data as { path?: unknown[] } | undefined)?.path;
  return Array.isArray(path) && path.length > 0 ? path.length : 1;
}

export function depthStackLayout(nodes: Node[], edges: Edge[]): LayoutResult {
  const stores = nodes.filter((n) => n.type === 'store');
  const procs = nodes.filter((n) => n.type === 'process');

  // Band stores by depth. Depths sorted ascending → band 0 is the outermost.
  const byDepth = new Map<number, Node[]>();
  for (const s of stores) {
    const d = depthOf(s);
    (byDepth.get(d) ?? byDepth.set(d, []).get(d)!).push(s);
  }
  const depths = [...byDepth.keys()].sort((a, b) => a - b);

  const boxes = new Map<string, Box>();
  const centerX = new Map<string, number>();  // store id → center x (for process seeding)
  let bandTop = 0;
  for (const d of depths) {
    const band = byDepth.get(d)!.sort((a, b) => (a.id < b.id ? -1 : 1));
    const bandH = band.reduce((m, s) => Math.max(m, fullFootprint(s).h), 0);
    let x = 0;
    for (const s of band) {
      const f = fullFootprint(s);
      boxes.set(s.id, { id: s.id, x, y: bandTop, w: f.w, h: f.h });
      centerX.set(s.id, x + f.w / 2);
      x += f.w + H_GAP;
    }
    bandTop += bandH + BAND_V_GAP;
  }

  // Which stores each process wires to (either wire direction).
  const procStores = new Map<string, string[]>();
  for (const e of edges) {
    const kind = (e.data as { edgeType?: string } | undefined)?.edgeType;
    if (kind !== 'input' && kind !== 'output') continue;
    const proc = kind === 'input' ? e.target : e.source;
    const store = kind === 'input' ? e.source : e.target;
    if (!centerX.has(store)) continue;
    (procStores.get(proc) ?? procStores.set(proc, []).get(proc)!).push(store);
  }

  // Seed each process below the store bands, under the mean x of its stores.
  const procTop = bandTop + PROC_GAP;
  for (const p of procs.slice().sort((a, b) => (a.id < b.id ? -1 : 1))) {
    const f = fullFootprint(p);
    const cs = procStores.get(p.id) ?? [];
    const meanCx = cs.length
      ? cs.reduce((s, id) => s + (centerX.get(id) ?? 0), 0) / cs.length
      : 0;
    boxes.set(p.id, { id: p.id, x: meanCx - f.w / 2, y: procTop, w: f.w, h: f.h });
  }

  // Guarantee no overlaps, then normalize to a positive origin.
  const items = [...boxes.values()];
  removeOverlaps(items, MARGIN, 400);
  let minX = Infinity, minY = Infinity;
  for (const b of items) { if (b.x < minX) minX = b.x; if (b.y < minY) minY = b.y; }
  if (!Number.isFinite(minX)) { minX = 0; minY = 0; }

  const posById = new Map(items.map((b) => [b.id, { x: b.x - minX, y: b.y - minY }]));
  const laidOut = nodes.map((n) => {
    const p = posById.get(n.id);
    return p ? { ...n, position: p } : n;
  });
  return { nodes: laidOut };
}

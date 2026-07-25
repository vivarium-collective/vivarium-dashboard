// src/layouts/egoLayout.ts — "center on this process" LOCAL rearrangement.
//
// The process stays exactly where it is, and only ITS connected stores are
// pulled in to flank it:
//   - stores it ONLY reads  → a column on the LEFT  (feed the process)
//   - stores it ONLY writes  → a column on the RIGHT (its results)
//   - stores it reads AND writes → a row BELOW it (read-modify-write state)
// EVERY OTHER NODE IS LEFT UNTOUCHED — the returned map contains only the moved
// stores, so the caller keeps all other nodes (processes + unrelated stores) in
// their existing positions. A purely local move around the focused process.
//
// Pure: no React, no DOM. Positions are React-Flow node TOP-LEFT coordinates.

import type { Node, Edge } from '@xyflow/react';
import { fullFootprint } from './clusterGrid';

export interface EgoLayout {
  /** Node id → new top-left position, ONLY for the process's stores that moved.
   *  Every other node is absent, so the caller leaves it in place. */
  positions: Map<string, { x: number; y: number }>;
  /** The focused process plus its stores — what the caller should fitView to. */
  egoIds: string[];
}

/** Horizontal gap between the process card and a store column. */
const COL_GAP = 140;
/** Vertical gap between stacked cards in a column. */
const ROW_GAP = 32;
/** Gap between the process and the shared (read+write) row below it. */
const SHARED_GAP = 90;

interface Sized { id: string; w: number; h: number }

/** Stack a column of sized boxes, vertically centered on `cy`, at fixed `cx`
 *  (both are CENTER coordinates); write TOP-LEFT positions into `out`. */
function stackColumn(
  items: Sized[], cx: number, cy: number,
  out: Map<string, { x: number; y: number }>,
): void {
  const total = items.reduce((s, it) => s + it.h, 0) + ROW_GAP * Math.max(0, items.length - 1);
  let y = cy - total / 2;
  for (const it of items) {
    out.set(it.id, { x: cx - it.w / 2, y });
    y += it.h + ROW_GAP;
  }
}

/** Lay a row of sized boxes, horizontally centered on `cx`, at fixed `cy`
 *  (CENTER coordinates); write TOP-LEFT positions into `out`. */
function layRow(
  items: Sized[], cx: number, cy: number,
  out: Map<string, { x: number; y: number }>,
): void {
  const total = items.reduce((s, it) => s + it.w, 0) + ROW_GAP * Math.max(0, items.length - 1);
  let x = cx - total / 2;
  for (const it of items) {
    out.set(it.id, { x, y: cy - it.h / 2 });
    x += it.w + ROW_GAP;
  }
}

export function egoLayout(nodes: Node[], edges: Edge[], procId: string): EgoLayout {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const proc = byId.get(procId);
  if (!proc) return { positions: new Map(), egoIds: [] };

  // Classify the process's stores from its wire edges. For an input edge the
  // store is the source; for an output edge the store is the target.
  const inputs = new Set<string>();
  const outputs = new Set<string>();
  for (const e of edges) {
    const kind = (e.data as { edgeType?: string } | undefined)?.edgeType;
    if (kind === 'input' && e.target === procId && byId.has(e.source)) inputs.add(e.source);
    else if (kind === 'output' && e.source === procId && byId.has(e.target)) outputs.add(e.target);
  }
  // Ties broken lexically for a deterministic, stable arrangement.
  const bidir = [...inputs].filter((s) => outputs.has(s)).sort();
  const leftOnly = [...inputs].filter((s) => !outputs.has(s)).sort();
  const rightOnly = [...outputs].filter((s) => !inputs.has(s)).sort();

  const sized = (id: string): Sized => {
    const f = fullFootprint(byId.get(id)!);
    return { id, w: f.w, h: f.h };
  };
  const pf = fullFootprint(proc);
  // The process STAYS PUT — everything is placed relative to its current center.
  const pcx = proc.position.x + pf.w / 2;
  const pcy = proc.position.y + pf.h / 2;

  const positions = new Map<string, { x: number; y: number }>();

  const leftItems = leftOnly.map(sized);
  const rightItems = rightOnly.map(sized);
  const bidirItems = bidir.map(sized);

  const maxStoreW = [...leftItems, ...rightItems].reduce((m, it) => Math.max(m, it.w), 0);
  const colDX = pf.w / 2 + COL_GAP + maxStoreW / 2;
  stackColumn(leftItems, pcx - colDX, pcy, positions);
  stackColumn(rightItems, pcx + colDX, pcy, positions);

  if (bidirItems.length) {
    const maxH = bidirItems.reduce((m, it) => Math.max(m, it.h), 0);
    layRow(bidirItems, pcx, proc.position.y + pf.h + SHARED_GAP + maxH / 2, positions);
  }

  // positions holds ONLY the moved stores; the process and every other node are
  // deliberately absent so the caller leaves them exactly where they are.
  const egoIds = [procId, ...leftOnly, ...rightOnly, ...bidir];
  return { positions, egoIds };
}

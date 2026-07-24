// src/layouts/egoLayout.ts — "center on this process" arrangement.
//
// Given one focused process, lay its wiring out as a readable ego graph:
//   - stores it ONLY reads  → a column on the LEFT  (feed the process)
//   - stores it ONLY writes  → a column on the RIGHT (its results)
//   - stores it reads AND writes → a row BELOW it (read-modify-write state)
//   - the process itself centered between them
// Every other node is parked in a compact grid well to the right, out of the
// ego frame, so the caller can fitView() to just the ego set and get a clean
// bipartite-ish picture. This is honest about processes (like equilibrium)
// that mostly update stores in place: those stores land in the shared row
// rather than being forced onto one side.
//
// Pure: no React, no DOM. Positions are React-Flow node TOP-LEFT coordinates.

import type { Node, Edge } from '@xyflow/react';
import { fullFootprint } from './clusterGrid';

export interface EgoLayout {
  /** Node id → new top-left position for EVERY node (ego set + parked rest). */
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
/** Clearance between the ego frame and the parked-rest grid. */
const PARK_GAP = 480;
const PARK_COLS = 6;
const PARK_CELL = 200;

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

  const positions = new Map<string, { x: number; y: number }>();
  // Process centered at the origin (CENTER (0,0) → top-left offset).
  positions.set(procId, { x: -pf.w / 2, y: -pf.h / 2 });

  const leftItems = leftOnly.map(sized);
  const rightItems = rightOnly.map(sized);
  const bidirItems = bidir.map(sized);

  const maxStoreW = [...leftItems, ...rightItems].reduce((m, it) => Math.max(m, it.w), 0);
  const colDX = pf.w / 2 + COL_GAP + maxStoreW / 2;
  stackColumn(leftItems, -colDX, 0, positions);
  stackColumn(rightItems, colDX, 0, positions);

  if (bidirItems.length) {
    const maxH = bidirItems.reduce((m, it) => Math.max(m, it.h), 0);
    layRow(bidirItems, 0, pf.h / 2 + SHARED_GAP + maxH / 2, positions);
  }

  const egoIds = [procId, ...leftOnly, ...rightOnly, ...bidir];

  // Park everything else in a compact grid to the right of the ego frame so it
  // never overlaps the arrangement (and fitView-to-ego stays clean).
  const egoSet = new Set(egoIds);
  let egoRight = -Infinity;
  let egoTop = Infinity;
  for (const id of egoIds) {
    const p = positions.get(id)!;
    const f = fullFootprint(byId.get(id)!);
    egoRight = Math.max(egoRight, p.x + f.w);
    egoTop = Math.min(egoTop, p.y);
  }
  const parkX0 = egoRight + PARK_GAP;
  const parked = nodes.filter((n) => !egoSet.has(n.id)).sort((a, b) => (a.id < b.id ? -1 : 1));
  parked.forEach((n, i) => {
    const col = i % PARK_COLS;
    const row = Math.floor(i / PARK_COLS);
    positions.set(n.id, { x: parkX0 + col * PARK_CELL, y: egoTop + row * PARK_CELL });
  });

  return { positions, egoIds };
}

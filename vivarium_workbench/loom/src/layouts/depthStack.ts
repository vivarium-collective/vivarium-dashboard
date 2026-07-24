// src/layouts/depthStack.ts — "stack stores by depth" as a tidy TREE.
//
// A structural alternative to the force overview: stores are arranged as a
// nesting tree — top-level (root) stores side-by-side across the top, and each
// store's children clustered directly beneath IT (recursively), so a store and
// its whole subtree read as one tight cluster. Processes are seeded in a band
// below the tree, near the stores they wire, and de-overlapped among themselves
// (the tree itself is overlap-free by construction and left untouched).
//
// Pure: no React, no DOM. Returns React-Flow node TOP-LEFT positions.

import type { Node, Edge } from '@xyflow/react';
import { fullFootprint, type Box } from './clusterGrid';
import type { LayoutResult } from './types';

/** Gap between sibling subtrees. */
const SIB_GAP = 26;
/** Gap between separate root trees across the top. */
const ROOT_GAP = 64;
/** Vertical gap between tree levels. */
const LEVEL_GAP = 66;
/** Gap below the deepest store level to the process band. */
const PROC_GAP = 130;
/** Overlap clearance enforced among processes. */
const PROC_MARGIN = 34;

const byId = (a: Node, b: Node) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
const pathKey = (p: unknown[]) => p.join('');

export function depthStackLayout(nodes: Node[], edges: Edge[]): LayoutResult {
  const stores = nodes.filter((n) => n.type === 'store');
  const procs = nodes.filter((n) => n.type === 'process');
  const storeH = stores.length ? fullFootprint(stores[0]).h : 150;

  // Build the store tree from bigraph paths: a store's parent is the store whose
  // path is this store's path minus its last segment.
  const byPath = new Map<string, Node>();
  for (const s of stores) {
    const p = (s.data as { path?: unknown[] } | undefined)?.path;
    if (Array.isArray(p) && p.length) byPath.set(pathKey(p), s);
  }
  const kids = new Map<string, Node[]>();
  const roots: Node[] = [];
  for (const s of stores) {
    const p = (s.data as { path?: unknown[] } | undefined)?.path;
    const parent = Array.isArray(p) && p.length > 1 ? byPath.get(pathKey(p.slice(0, -1))) : undefined;
    if (parent) {
      const arr = kids.get(parent.id) ?? [];
      arr.push(s);
      kids.set(parent.id, arr);
    } else {
      roots.push(s);
    }
  }
  for (const arr of kids.values()) arr.sort(byId);
  roots.sort(byId);

  // Tidy-tree subtree widths (post-order): a subtree is as wide as the wider of
  // the node itself and the packed row of its children's subtrees.
  const subW = new Map<string, number>();
  const widthOf = (s: Node): number => {
    const cached = subW.get(s.id);
    if (cached != null) return cached;
    const f = fullFootprint(s);
    const ch = kids.get(s.id) ?? [];
    let w = f.w;
    if (ch.length) {
      const row = ch.reduce((sum, k) => sum + widthOf(k), 0) + SIB_GAP * (ch.length - 1);
      w = Math.max(f.w, row);
    }
    subW.set(s.id, w);
    return w;
  };

  const boxes = new Map<string, Box>();
  const place = (s: Node, left: number, depth: number) => {
    const f = fullFootprint(s);
    const w = widthOf(s);
    // Center the node over its own subtree; children packed centered below.
    boxes.set(s.id, { id: s.id, x: left + (w - f.w) / 2, y: depth * (storeH + LEVEL_GAP), w: f.w, h: f.h });
    const ch = kids.get(s.id) ?? [];
    if (ch.length) {
      const rowW = ch.reduce((sum, k) => sum + widthOf(k), 0) + SIB_GAP * (ch.length - 1);
      let cl = left + (w - rowW) / 2;
      for (const k of ch) { place(k, cl, depth + 1); cl += widthOf(k) + SIB_GAP; }
    }
  };
  let rootLeft = 0;
  for (const r of roots) { place(r, rootLeft, 0); rootLeft += widthOf(r) + ROOT_GAP; }

  // Processes go in a GRID strictly BELOW the whole store tree, so they never
  // overlap the stores (a hard guarantee — packed, not force-relaxed, so nothing
  // can drift up into a store row). Ordered by the mean x of the stores they
  // wire, so each roughly sits under the stores it touches.
  const centerX = new Map<string, number>();
  let treeBottom = 0, treeLeft = Infinity, treeRight = -Infinity;
  for (const [id, b] of boxes) {
    centerX.set(id, b.x + b.w / 2);
    treeBottom = Math.max(treeBottom, b.y + b.h);
    treeLeft = Math.min(treeLeft, b.x);
    treeRight = Math.max(treeRight, b.x + b.w);
  }
  if (!Number.isFinite(treeLeft)) { treeLeft = 0; treeRight = 0; }

  const procStores = new Map<string, string[]>();
  for (const e of edges) {
    const kind = (e.data as { edgeType?: string } | undefined)?.edgeType;
    if (kind !== 'input' && kind !== 'output') continue;
    const proc = kind === 'input' ? e.target : e.source;
    const store = kind === 'input' ? e.source : e.target;
    if (!centerX.has(store)) continue;
    const arr = procStores.get(proc) ?? [];
    arr.push(store);
    procStores.set(proc, arr);
  }
  const meanX = (p: Node) => {
    const cs = procStores.get(p.id) ?? [];
    return cs.length ? cs.reduce((s, id) => s + (centerX.get(id) ?? 0), 0) / cs.length : 0;
  };
  const procSorted = procs.slice().sort((a, b) => (meanX(a) - meanX(b)) || byId(a, b));

  // Pack left→right into rows whose width tracks the tree's, wrapping downward.
  const rowMax = Math.max(treeRight - treeLeft, 900);
  let px = treeLeft, py = treeBottom + PROC_GAP, rowH = 0;
  for (const p of procSorted) {
    const f = fullFootprint(p);
    if (px > treeLeft && px + f.w - treeLeft > rowMax) { px = treeLeft; py += rowH + PROC_MARGIN; rowH = 0; }
    boxes.set(p.id, { id: p.id, x: px, y: py, w: f.w, h: f.h });
    px += f.w + PROC_MARGIN;
    rowH = Math.max(rowH, f.h);
  }

  // Normalize to a positive origin.
  const items = [...boxes.values()];
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

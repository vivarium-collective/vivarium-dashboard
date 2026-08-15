// Quality guard for the Tree / Grid hierarchy layouts. The FIRST attempt at
// these modes was reverted because it collapsed on large / hub-heavy composites:
// a linear place graph became a thin overlapping column, and processes dropped
// at wire-centroids then a global force-push got flung far outside the frame.
// This file asserts the two properties that class of bug violates — NO OVERLAPS
// and a BOUNDED, non-degenerate frame — on the real v2ecoli baseline AND on the
// degenerate place-graph shapes (linear chain, DAG, forest) that broke it. If it
// fails, the layout regressed toward the collapse — fix the geometry, don't relax
// the bounds.
import { describe, it, expect } from 'vitest';
import type { Node, Edge } from '@xyflow/react';
import { stateToReactFlow } from '../convert';
import { treeMode, gridMode, treeFootprint, gridEdgeVisibility } from '../layouts/treeFlow';
import fixture from './fixtures/v2ecoli-baseline.json';

type Box = { id: string; x: number; y: number; w: number; h: number };

function boxesOf(nodes: Node[]): Box[] {
  return nodes.map((n) => {
    const f = treeFootprint(n);
    return { id: n.id, x: n.position.x, y: n.position.y, w: f.w, h: f.h };
  });
}

/** Overlapping pairs, with a tiny epsilon so exact-touch edges don't count. */
function overlaps(boxes: Box[]): Array<[string, string]> {
  const eps = 0.5;
  const out: Array<[string, string]> = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.x < b.x + b.w - eps && b.x < a.x + a.w - eps &&
          a.y < b.y + b.h - eps && b.y < a.y + a.h - eps) out.push([a.id, b.id]);
    }
  }
  return out;
}

function bbox(boxes: Box[]) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const b of boxes) {
    minX = Math.min(minX, b.x); minY = Math.min(minY, b.y);
    maxX = Math.max(maxX, b.x + b.w); maxY = Math.max(maxY, b.y + b.h);
  }
  return { w: maxX - minX, h: maxY - minY };
}

/** Total node area / bbox area. A "flung far" node blows up the bbox and drops
 *  this toward 0; a healthy pack sits well above it. */
function density(boxes: Box[]): number {
  const area = boxes.reduce((a, b) => a + b.w * b.h, 0);
  const bb = bbox(boxes);
  return area / (bb.w * bb.h);
}

async function assertHealthy(nodes: Node[], edges: Edge[], mode: typeof treeMode, tag: string) {
  const { nodes: out } = await mode.run(nodes, edges, { compositeId: tag, tier: 'full', granularity: 0.5 });
  // Every node placed at a finite position.
  for (const n of out) {
    expect(Number.isFinite(n.position.x), `${tag}: ${n.id}.x finite`).toBe(true);
    expect(Number.isFinite(n.position.y), `${tag}: ${n.id}.y finite`).toBe(true);
  }
  const boxes = boxesOf(out);
  // No overlaps — the property the collapse violated.
  const ov = overlaps(boxes);
  expect(ov.slice(0, 8), `${tag}: overlapping pairs`).toEqual([]);
  // Non-degenerate frame: neither a thin column nor a thin row (the "thin
  // overlapping column" failure). Allow tall-ish hierarchies but not extreme.
  const bb = bbox(boxes);
  const aspect = bb.w / bb.h;
  expect(aspect, `${tag}: aspect w/h`).toBeGreaterThan(0.05);
  expect(aspect, `${tag}: aspect w/h`).toBeLessThan(20);
  // Bounded: nothing flung far. A single escaped node craters the density.
  if (boxes.length > 3) expect(density(boxes), `${tag}: density`).toBeGreaterThan(0.03);
  return out;
}

// ── Synthetic place-graph shapes (the cases that broke the first attempt) ──
function store(id: string): Node {
  return { id, type: 'store', position: { x: 0, y: 0 }, data: { label: id } } as Node;
}
function proc(id: string, ports: string[]): Node {
  return { id, type: 'process', position: { x: 0, y: 0 },
    data: { label: id, inputPorts: ports, outputPorts: ports } } as Node;
}
function place(a: string, b: string): Edge {
  return { id: `pl-${a}-${b}`, source: a, target: b, data: { edgeType: 'place' } } as Edge;
}
function wire(store_: string, procId: string): Edge {
  return { id: `w-${store_}-${procId}`, source: store_, target: procId, data: { edgeType: 'input' } } as Edge;
}

describe('Tree / Grid layout — no collapse on the v2ecoli baseline', () => {
  const { nodes, edges } = stateToReactFlow((fixture as any).state);
  const N = nodes as unknown as Node[];
  const E = edges as unknown as Edge[];
  it('Tree: no overlaps, bounded frame on 46-process hub-heavy composite', async () => {
    await assertHealthy(N, E, treeMode, 'v2ecoli/tree');
  });
  it('Grid: no overlaps, bounded frame on 46-process hub-heavy composite', async () => {
    await assertHealthy(N, E, gridMode, 'v2ecoli/grid');
  });
});

describe('Tree / Grid layout — robust on degenerate place graphs', () => {
  // A deep LINEAR chain: the shape the first attempt collapsed into a thin
  // overlapping column.
  const chainStores = Array.from({ length: 8 }, (_, i) => store(`s${i}`));
  const chainEdges = Array.from({ length: 7 }, (_, i) => place(`s${i}`, `s${i + 1}`));
  const chainProcs = Array.from({ length: 6 }, (_, i) => proc(`p${i}`, ['a', 'b', 'c']));
  const chainWires = chainProcs.map((p, i) => wire(`s${i}`, p.id));

  it('Tree: a linear place chain does not overlap', async () => {
    await assertHealthy([...chainStores, ...chainProcs], [...chainEdges, ...chainWires], treeMode, 'chain/tree');
  });
  it('Grid: a linear place chain does not overlap', async () => {
    await assertHealthy([...chainStores, ...chainProcs], [...chainEdges, ...chainWires], gridMode, 'chain/grid');
  });

  it('Tree: a place-DAG (a store with two parents) resolves without overlap', async () => {
    const s = ['r', 'a', 'b', 'shared'].map(store);
    const e = [place('r', 'a'), place('r', 'b'), place('a', 'shared'), place('b', 'shared')];
    await assertHealthy(s, e, treeMode, 'dag/tree');
  });

  it('Tree: a forest (many roots, no place edges) fans wide, not tall', async () => {
    const s = Array.from({ length: 12 }, (_, i) => store(`r${i}`));
    const p = Array.from({ length: 12 }, (_, i) => proc(`q${i}`, ['x']));
    const w = p.map((pp, i) => wire(`r${i}`, pp.id));
    await assertHealthy([...s, ...p], w, treeMode, 'forest/tree');
  });

  it('handles the empty graph', async () => {
    const { nodes: out } = await treeMode.run([], [], { compositeId: null, tier: 'full', granularity: 0.5 });
    expect(out).toEqual([]);
  });
});

describe('Grid edge visibility — clean catalog, wires on focus', () => {
  const edges: Edge[] = [
    place('r', 'a'), place('r', 'b'),           // tree skeleton (store→store)
    wire('a', 'p1'),                            // p1 reads store a
    { id: 'w-p1-b', source: 'p1', target: 'b', data: { edgeType: 'output' } } as Edge, // p1 writes b
    wire('b', 'p2'),                            // p2 reads store b
  ];
  const noFocus = { focused: new Set<string>(), pinned: new Set<string>() };

  it('with nothing focused, draws ONLY place edges (hides every wire)', () => {
    const out = gridEdgeVisibility(edges, noFocus, []);
    expect(out.map((e) => e.id).sort()).toEqual(['pl-r-a', 'pl-r-b']);
  });

  it('focusing a process reveals just its wires (stamped _focused), keeps place edges', () => {
    const out = gridEdgeVisibility(edges, { focused: new Set(['p1']), pinned: new Set() }, []);
    const ids = out.map((e) => e.id).sort();
    expect(ids).toEqual(['pl-r-a', 'pl-r-b', 'w-a-p1', 'w-p1-b']); // p2's wire stays hidden
    for (const e of out) {
      if ((e.data as { edgeType?: string }).edgeType !== 'place') {
        expect((e.data as { _focused?: boolean })._focused).toBe(true);
      }
    }
  });
});

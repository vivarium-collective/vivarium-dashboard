import { describe, it, expect } from 'vitest';
import type { Node, Edge } from '@xyflow/react';
import { processColumnMode } from '../layouts/processColumn';
import { hierarchyMode } from '../layouts/hierarchy';
import { clusterGridMode, clusterGridEdgeVisibility } from '../layouts/clusterGrid';
import { hubStoreIds } from '../storeFacts';

const nodes: Node[] = [
  { id: 'p1', type: 'process', position: { x: 0, y: 0 },
    data: { label: 'p1', inputPortsSchema: { a: 'unique.RNA' }, outputPortsSchema: {} } },
  { id: 'p2', type: 'process', position: { x: 0, y: 0 },
    data: { label: 'p2', inputPortsSchema: { a: 'unique.RNA' }, outputPortsSchema: {} } },
  { id: 'unique.RNA', type: 'store', position: { x: 0, y: 0 }, data: { label: 'RNA' } },
] as unknown as Node[];

const edges: Edge[] = [
  { id: 'p1--in--a', source: 'unique.RNA', target: 'p1', data: { edgeType: 'input' } },
  { id: 'p1--in--b', source: 'unique.RNA', target: 'p1', data: { edgeType: 'input' } },
  { id: 'p2--in--a', source: 'unique.RNA', target: 'p2', data: { edgeType: 'input' } },
  { id: 'place--r--c', source: 'unique', target: 'unique.RNA', data: { edgeType: 'place' } },
] as unknown as Edge[];

const vis = processColumnMode.edgeVisibility!;

describe('process-column edge visibility', () => {
  it('drops wire edges when nothing is focused', () => {
    const out = vis(edges, { focused: new Set(), pinned: new Set() }, nodes);
    expect(out.some((e) => (e.data as any).edgeType === 'input')).toBe(false);
  });

  it('always keeps structural place edges', () => {
    const out = vis(edges, { focused: new Set(), pinned: new Set() }, nodes);
    expect(out.find((e) => e.id === 'place--r--c')).toBeTruthy();
  });

  it('shows only the focused process wires at full strength', () => {
    const out = vis(edges, { focused: new Set(['p1']), pinned: new Set() }, nodes);
    const ids = out.filter((e) => (e.data as any).edgeType === 'input').map((e) => e.id);
    expect(ids).toEqual(expect.arrayContaining(['p1--in--a', 'p1--in--b']));
    expect(ids).not.toContain('p2--in--a');
  });

  it('unions pinned processes with focused ones', () => {
    const out = vis(edges, { focused: new Set(['p1']), pinned: new Set(['p2']) }, nodes);
    const ids = out.filter((e) => (e.data as any).edgeType === 'input').map((e) => e.id);
    expect(ids).toContain('p1--in--a');
    expect(ids).toContain('p2--in--a');
  });

  it('keeps output wires of a focused process too', () => {
    const withOut = [
      ...edges,
      { id: 'p1--out--z', source: 'p1', target: 'unique.RNA',
        data: { edgeType: 'output' } } as unknown as Edge,
    ];
    const out = vis(withOut, { focused: new Set(['p1']), pinned: new Set() }, nodes);
    expect(out.find((e) => e.id === 'p1--out--z')).toBeTruthy();
  });

  it('returns the SAME array identity when nothing is culled', () => {
    // Cheap-render guarantee: a pass-through must not mint a new array, or
    // React Flow re-derives its whole edge store on every hover/drag frame.
    const placeOnly = edges.filter((e) => (e.data as any).edgeType === 'place');
    expect(vis(placeOnly, { focused: new Set(), pinned: new Set() }, nodes)).toBe(placeOnly);
  });

  it('is focus-driven (App wires up hover/hint/pins for it)', () => {
    expect(processColumnMode.focusReveals).toBe(true);
  });
});

// A hub store touched by >= max(3, round(0.30*n)) processes. Four processes,
// each wiring to the shared `bulk` hub AND to its own private store; n=4 →
// hubCut = max(3, round(1.2)) = 3, so `bulk` (4 touches) is a hub and each
// private store (1 touch) is not.
const hubNodes: Node[] = [
  { id: 'bulk', type: 'store', position: { x: 0, y: 0 }, data: { label: 'bulk' } },
  { id: 's1', type: 'store', position: { x: 0, y: 0 }, data: { label: 's1' } },
  { id: 's2', type: 'store', position: { x: 0, y: 0 }, data: { label: 's2' } },
  { id: 's3', type: 'store', position: { x: 0, y: 0 }, data: { label: 's3' } },
  { id: 's4', type: 'store', position: { x: 0, y: 0 }, data: { label: 's4' } },
  { id: 'p1', type: 'process', position: { x: 0, y: 0 }, data: { label: 'p1' } },
  { id: 'p2', type: 'process', position: { x: 0, y: 0 }, data: { label: 'p2' } },
  { id: 'p3', type: 'process', position: { x: 0, y: 0 }, data: { label: 'p3' } },
  { id: 'p4', type: 'process', position: { x: 0, y: 0 }, data: { label: 'p4' } },
] as unknown as Node[];

const hubEdges: Edge[] = [
  { id: 'p1--in--bulk', source: 'bulk', target: 'p1', data: { edgeType: 'input' } },
  { id: 'p2--in--bulk', source: 'bulk', target: 'p2', data: { edgeType: 'input' } },
  { id: 'p3--in--bulk', source: 'bulk', target: 'p3', data: { edgeType: 'input' } },
  { id: 'p4--out--bulk', source: 'p4', target: 'bulk', data: { edgeType: 'output' } },
  { id: 'p1--in--s1', source: 's1', target: 'p1', data: { edgeType: 'input' } },
  { id: 'p2--in--s2', source: 's2', target: 'p2', data: { edgeType: 'input' } },
  { id: 'p3--in--s3', source: 's3', target: 'p3', data: { edgeType: 'input' } },
  { id: 'p4--out--s4', source: 'p4', target: 's4', data: { edgeType: 'output' } },
  { id: 'place--r--bulk', source: 'root', target: 'bulk', data: { edgeType: 'place' } },
] as unknown as Edge[];

const noFocus = { focused: new Set<string>(), pinned: new Set<string>() };

describe('hub-store detection', () => {
  it('flags a store touched by >= the hub cutoff of processes', () => {
    const hubs = hubStoreIds(hubEdges);
    expect(hubs.has('bulk')).toBe(true);
  });

  it('does not flag a store only one or two processes touch', () => {
    const hubs = hubStoreIds(hubEdges);
    for (const s of ['s1', 's2', 's3', 's4']) expect(hubs.has(s)).toBe(false);
  });

  it('never forms a hub in a tiny graph (the max(3, …) floor)', () => {
    // One process, one store — the whole store is "touched by everything",
    // but the floor of 3 keeps it from being a hub (identity-passthrough).
    const tiny: Edge[] = [
      { id: 'e', source: 's', target: 'p', data: { edgeType: 'input' } },
    ] as unknown as Edge[];
    expect(hubStoreIds(tiny).size).toBe(0);
  });
});

describe('hierarchy edge visibility', () => {
  const vis = hierarchyMode.edgeVisibility!;

  it('exists — hierarchy now culls hub-store wires', () => {
    expect(hierarchyMode.edgeVisibility).toBeDefined();
  });

  it('is NOT focus-driven (hierarchy hub-hiding is toggle-only)', () => {
    // focusReveals stays falsy, so App keeps hover/hint/pins off in hierarchy.
    expect(hierarchyMode.focusReveals).toBeFalsy();
  });

  it('drops wires whose store endpoint is a hub, by default', () => {
    const out = vis(hubEdges, noFocus, hubNodes);
    const ids = out.map((e) => e.id);
    expect(ids).not.toContain('p1--in--bulk');
    expect(ids).not.toContain('p2--in--bulk');
    expect(ids).not.toContain('p3--in--bulk');
    expect(ids).not.toContain('p4--out--bulk');
  });

  it('keeps place edges AND non-hub wires', () => {
    const out = vis(hubEdges, noFocus, hubNodes);
    const ids = out.map((e) => e.id);
    expect(ids).toContain('place--r--bulk');       // structural place edge
    expect(ids).toContain('p1--in--s1');            // non-hub wire
    expect(ids).toContain('p4--out--s4');           // non-hub wire
  });

  it('shows ALL edges (identity) when the toggle is on', () => {
    const out = vis(hubEdges, { ...noFocus, showHubWires: true }, hubNodes);
    expect(out).toBe(hubEdges);
  });

  it('ignores focus/pins — hub-hiding is structural, not focus-driven', () => {
    const focused = vis(hubEdges, { focused: new Set(['p1']), pinned: new Set() }, hubNodes);
    const plain = vis(hubEdges, noFocus, hubNodes);
    // Same set of ids regardless of focus (a hovered process reveals nothing).
    expect(focused.map((e) => e.id).sort()).toEqual(plain.map((e) => e.id).sort());
  });

  it('returns the SAME array identity when there is no hub to hide', () => {
    const tiny: Edge[] = [
      { id: 'e', source: 's', target: 'p', data: { edgeType: 'input' } },
      { id: 'pl', source: 'r', target: 's', data: { edgeType: 'place' } },
    ] as unknown as Edge[];
    expect(vis(tiny, noFocus, hubNodes)).toBe(tiny);
  });
});

// The sole canvas layout (clusterGridMode) is focus-driven: the default view
// keeps the hub-hidden declutter, and focusing a process reveals + HIGHLIGHTS
// all its wires (hub wires included). Reuses the same hub fixtures above.
describe('cluster-grid edge visibility (focus-driven reveal + highlight)', () => {
  it('is focus-driven so App wires up hover / hint / pins', () => {
    expect(clusterGridMode.focusReveals).toBe(true);
  });

  it('hides hub-store wires by default (nothing focused)', () => {
    const out = clusterGridEdgeVisibility(hubEdges, noFocus, hubNodes);
    const ids = out.map((e) => e.id);
    expect(ids).not.toContain('p1--in--bulk');
    expect(ids).not.toContain('p4--out--bulk');
    // non-hub wires + place edges survive the declutter
    expect(ids).toContain('p1--in--s1');
    expect(ids).toContain('place--r--bulk');
  });

  it('leaves no edge flagged _focused when nothing is focused', () => {
    const out = clusterGridEdgeVisibility(hubEdges, noFocus, hubNodes);
    expect(out.some((e) => (e.data as any)?._focused)).toBe(false);
  });

  it('returns SAME identity in the no-focus, no-hub pass-through', () => {
    const tiny: Edge[] = [
      { id: 'e', source: 's', target: 'p', data: { edgeType: 'input' } },
      { id: 'pl', source: 'r', target: 's', data: { edgeType: 'place' } },
    ] as unknown as Edge[];
    expect(clusterGridEdgeVisibility(tiny, noFocus, hubNodes)).toBe(tiny);
  });

  it('REVEALS a focused process\'s hub wire and flags it _focused', () => {
    const out = clusterGridEdgeVisibility(
      hubEdges, { focused: new Set(['p1']), pinned: new Set() }, hubNodes,
    );
    const bulk = out.find((e) => e.id === 'p1--in--bulk');
    // p1's normally-hidden hub wire is now drawn...
    expect(bulk).toBeTruthy();
    // ...and highlighted.
    expect((bulk!.data as any)._focused).toBe(true);
    // p1's non-hub wire is focused too.
    expect((out.find((e) => e.id === 'p1--in--s1')!.data as any)._focused).toBe(true);
  });

  it('keeps a NON-focused hub wire hidden while revealing the focused one', () => {
    const out = clusterGridEdgeVisibility(
      hubEdges, { focused: new Set(['p1']), pinned: new Set() }, hubNodes,
    );
    const ids = out.map((e) => e.id);
    // p1's hub wire revealed; p2/p3/p4's hub wires stay hidden (declutter intact).
    expect(ids).toContain('p1--in--bulk');
    expect(ids).not.toContain('p2--in--bulk');
    expect(ids).not.toContain('p4--out--bulk');
  });

  it('dims non-focused wires so the focused set stands out', () => {
    const out = clusterGridEdgeVisibility(
      hubEdges, { focused: new Set(['p1']), pinned: new Set() }, hubNodes,
    );
    const other = out.find((e) => e.id === 'p2--in--s2');
    expect((other!.data as any)._dim).toBe(true);
    expect((other!.data as any)._focused).toBe(false);
    // place edges are the structural skeleton — never dimmed.
    expect((out.find((e) => e.id === 'place--r--bulk')!.data as any)?._dim).toBeFalsy();
  });

  it('pins count as focus (a click-pinned process keeps its wires revealed)', () => {
    const out = clusterGridEdgeVisibility(
      hubEdges, { focused: new Set(), pinned: new Set(['p3']) }, hubNodes,
    );
    const hub = out.find((e) => e.id === 'p3--in--bulk');
    expect(hub).toBeTruthy();
    expect((hub!.data as any)._focused).toBe(true);
  });

  it('the "Show hub wires" toggle reveals ALL hub wires even off-focus', () => {
    const out = clusterGridEdgeVisibility(
      hubEdges, { focused: new Set(['p1']), pinned: new Set(), showHubWires: true }, hubNodes,
    );
    const ids = out.map((e) => e.id);
    expect(ids).toContain('p2--in--bulk');   // non-focused hub wire now shown
    expect(ids).toContain('p4--out--bulk');
  });
});

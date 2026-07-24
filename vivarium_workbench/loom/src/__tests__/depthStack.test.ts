import { describe, it, expect } from 'vitest';
import type { Node, Edge } from '@xyflow/react';
import { depthStackLayout } from '../layouts/depthStack';

// R is a top-level store (depth 1); RC is nested under it (depth 2). P wires both.
const storeAt = (id: string, path: string[]): Node => ({
  id, type: 'store', position: { x: 0, y: 0 }, data: { path },
});
const proc = (id: string): Node => ({
  id, type: 'process', position: { x: 0, y: 0 },
  data: { path: [id], inputPorts: ['x'], outputPorts: ['y'] },
});

const nodes: Node[] = [
  storeAt('R', ['R']),
  storeAt('RC', ['R', 'RC']),
  storeAt('S', ['S']),
  proc('P'),
];
const edges: Edge[] = [
  { id: 'e1', source: 'R', target: 'P', data: { edgeType: 'input' } },
  { id: 'e2', source: 'P', target: 'RC', data: { edgeType: 'output' } },
];

function pos(res: { nodes: Node[] }, id: string) {
  return res.nodes.find((n) => n.id === id)!.position;
}

describe('depthStackLayout', () => {
  it('bands stores by depth: outer (shallower) above inner (deeper)', () => {
    const res = depthStackLayout(nodes, edges);
    expect(pos(res, 'R').y).toBeLessThan(pos(res, 'RC').y);
    expect(pos(res, 'S').y).toBeLessThan(pos(res, 'RC').y);  // S is depth 1 too
  });

  it('places processes below the store bands', () => {
    const res = depthStackLayout(nodes, edges);
    expect(pos(res, 'P').y).toBeGreaterThan(pos(res, 'RC').y);
  });

  it('normalizes to a positive origin', () => {
    const res = depthStackLayout(nodes, edges);
    const xs = res.nodes.map((n) => n.position.x);
    const ys = res.nodes.map((n) => n.position.y);
    expect(Math.min(...xs)).toBe(0);
    expect(Math.min(...ys)).toBe(0);
  });

  it('produces no overlapping boxes (stores 168x150, process footprint)', () => {
    const res = depthStackLayout(nodes, edges);
    // Every store is 168x150; check no two nodes' 150x150 cores intersect.
    const boxes = res.nodes.map((n) => ({ x: n.position.x, y: n.position.y, w: 150, h: 130 }));
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
        expect(overlap).toBe(false);
      }
    }
  });

  it('is deterministic', () => {
    const a = depthStackLayout(nodes, edges);
    const b = depthStackLayout(nodes, edges);
    expect(a.nodes.map((n) => n.position)).toEqual(b.nodes.map((n) => n.position));
  });
});

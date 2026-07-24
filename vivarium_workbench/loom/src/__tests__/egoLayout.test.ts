import { describe, it, expect } from 'vitest';
import type { Node, Edge } from '@xyflow/react';
import { egoLayout } from '../layouts/egoLayout';

const proc = (id: string, inPorts: string[], outPorts: string[]): Node => ({
  id, type: 'process', position: { x: 0, y: 0 },
  data: { path: [id], inputPorts: inPorts, outputPorts: outPorts },
});
const store = (id: string): Node => ({
  id, type: 'store', position: { x: 0, y: 0 }, data: { path: [id] },
});
const wire = (id: string, source: string, target: string, kind: 'input' | 'output'): Edge => ({
  id, source, target, data: { edgeType: kind },
});

// P reads A, writes B, reads+writes C; D/Q are unrelated to P.
const nodes: Node[] = [
  proc('P', ['a', 'c_in'], ['b', 'c_out']),
  store('A'), store('B'), store('C'), store('D'), proc('Q', [], []),
];
const edges: Edge[] = [
  wire('e1', 'A', 'P', 'input'),
  wire('e2', 'P', 'B', 'output'),
  wire('e3', 'C', 'P', 'input'),
  wire('e4', 'P', 'C', 'output'),
  wire('e5', 'D', 'Q', 'input'),
];

describe('egoLayout', () => {
  it('classifies stores into left (read), right (write), and below (read+write)', () => {
    const { positions } = egoLayout(nodes, edges, 'P');
    const p = positions.get('P')!;
    const a = positions.get('A')!;   // input-only → left
    const b = positions.get('B')!;   // output-only → right
    const c = positions.get('C')!;   // read+write → below

    expect(a.x).toBeLessThan(p.x);
    expect(b.x).toBeGreaterThan(p.x);
    expect(c.y).toBeGreaterThan(p.y);
  });

  it('egoIds are the process plus its stores (not the unrelated ones)', () => {
    const { egoIds } = egoLayout(nodes, edges, 'P');
    expect(egoIds[0]).toBe('P');
    expect(new Set(egoIds)).toEqual(new Set(['P', 'A', 'B', 'C']));
    expect(egoIds).not.toContain('D');
    expect(egoIds).not.toContain('Q');
  });

  it('positions every node (ego set + parked rest) and parks non-ego far right', () => {
    const { positions } = egoLayout(nodes, edges, 'P');
    expect(positions.size).toBe(nodes.length);
    const b = positions.get('B')!;   // rightmost ego store
    // Parked nodes sit well beyond the ego frame.
    expect(positions.get('D')!.x).toBeGreaterThan(b.x);
    expect(positions.get('Q')!.x).toBeGreaterThan(b.x);
  });

  it('is deterministic', () => {
    const a = egoLayout(nodes, edges, 'P');
    const b = egoLayout(nodes, edges, 'P');
    expect([...a.positions.entries()]).toEqual([...b.positions.entries()]);
    expect(a.egoIds).toEqual(b.egoIds);
  });

  it('returns empty when the process is absent', () => {
    const { positions, egoIds } = egoLayout(nodes, edges, 'nope');
    expect(positions.size).toBe(0);
    expect(egoIds).toEqual([]);
  });
});

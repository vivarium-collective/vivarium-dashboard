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
    const proc = nodes.find((n) => n.id === 'P')!;   // stays put — not in positions
    const a = positions.get('A')!;   // input-only → left
    const b = positions.get('B')!;   // output-only → right
    const c = positions.get('C')!;   // read+write → below

    expect(positions.has('P')).toBe(false);        // the process is not moved
    expect(a.x).toBeLessThan(b.x);                 // input left of output
    expect(c.y).toBeGreaterThan(proc.position.y);  // read+write below the process
  });

  it('egoIds are the process plus its stores (not the unrelated ones)', () => {
    const { egoIds } = egoLayout(nodes, edges, 'P');
    expect(egoIds[0]).toBe('P');
    expect(new Set(egoIds)).toEqual(new Set(['P', 'A', 'B', 'C']));
    expect(egoIds).not.toContain('D');
    expect(egoIds).not.toContain('Q');
  });

  it('moves ONLY the process stores; leaves the process and every other node untouched', () => {
    const { positions } = egoLayout(nodes, edges, 'P');
    // Only the connected stores appear (they moved to flank the process);
    // the process itself and unrelated nodes are absent → kept in place.
    expect(new Set(positions.keys())).toEqual(new Set(['A', 'B', 'C']));
    expect(positions.has('P')).toBe(false);  // process stays put
    expect(positions.has('D')).toBe(false);  // unrelated store untouched
    expect(positions.has('Q')).toBe(false);  // other process untouched
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

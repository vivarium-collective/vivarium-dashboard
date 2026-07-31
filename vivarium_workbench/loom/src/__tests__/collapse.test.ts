import { describe, it, expect } from 'vitest';
import type { Node, Edge } from '@xyflow/react';
import { collapseStores, collapseProcesses } from '../collapse';

// A → sB (write), sB → C (read): process A writes store sB, process C reads it.
const nodes = [
  { id: 'A', type: 'process' },
  { id: 'C', type: 'process' },
  { id: 'sB', type: 'store' },
  { id: 'sIn', type: 'store' },
] as unknown as Node[];
// sIn → A (A reads sIn); A → sB (A writes sB); sB → C (C reads sB)
const edges = [
  { id: 'e1', source: 'sIn', target: 'A', data: { edgeType: 'input' } },
  { id: 'e2', source: 'A', target: 'sB', data: { edgeType: 'output' } },
  { id: 'e3', source: 'sB', target: 'C', data: { edgeType: 'input' } },
] as unknown as Edge[];

describe('collapseStores (process-only)', () => {
  it('drops stores and wires writer → reader', () => {
    const { nodes: n, edges: e } = collapseStores(nodes, edges);
    expect(n.map((x) => x.id).sort()).toEqual(['A', 'C']);   // only processes
    expect(e.map((x) => `${x.source}->${x.target}`)).toContain('A->C');  // A writes sB, C reads it
  });
});

describe('collapseProcesses (store-only)', () => {
  it('drops processes and wires read-store → write-store', () => {
    const { nodes: n, edges: e } = collapseProcesses(nodes, edges);
    expect(n.every((x) => x.type === 'store')).toBe(true);   // NO process nodes
    expect(n.map((x) => x.id).sort()).toEqual(['sB', 'sIn']);
    // A reads sIn and writes sB → sIn feeds sB.
    expect(e.map((x) => `${x.source}->${x.target}`)).toContain('sIn->sB');
  });
});

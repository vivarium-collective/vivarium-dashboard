// src/collapse.ts - graph collapse transforms for the Explore view.
//
//   collapseStores : the PROCESS-ONLY graph. Drop store nodes; for every store,
//     connect each writer process to each reader process (A writes store S, B
//     reads S => A -> B). Shows "who feeds whom" directly.
//
// The dual (processes -> hyperedges) is a RENDER mode, not a graph transform:
// App stamps process nodes at the 'glyph' tier so each process shrinks to a
// junction over the stores it touches (the store-centric hyperedge view).

import type { Node, Edge } from '@xyflow/react';

function addTo(m: Map<string, Set<string>>, k: string, v: string): void {
  let s = m.get(k);
  if (!s) { s = new Set(); m.set(k, s); }
  s.add(v);
}

export function collapseStores(
  nodes: Node[], edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  const procIds = new Set(nodes.filter((n) => n.type === 'process').map((n) => n.id));
  const writers = new Map<string, Set<string>>();  // store -> writer processes
  const readers = new Map<string, Set<string>>();  // store -> reader processes

  for (const e of edges) {
    const kind = (e.data as { edgeType?: string } | undefined)?.edgeType;
    if (kind === 'output' && procIds.has(e.source)) {
      addTo(writers, e.target, e.source);           // proc -> store
    } else if (kind === 'input' && procIds.has(e.target)) {
      addTo(readers, e.source, e.target);           // store -> proc
    } else if (kind === 'bidirectional') {
      const store = procIds.has(e.source) ? e.target : procIds.has(e.target) ? e.source : null;
      const proc = procIds.has(e.source) ? e.source : procIds.has(e.target) ? e.target : null;
      if (store && proc) { addTo(writers, store, proc); addTo(readers, store, proc); }
    }
  }

  const out: Edge[] = [];
  const seen = new Set<string>();
  for (const store of new Set<string>([...writers.keys(), ...readers.keys()])) {
    const ws = writers.get(store);
    const rs = readers.get(store);
    if (!ws || !rs) continue;
    for (const w of ws) {
      for (const r of rs) {
        if (w === r) continue;
        const k = w + '' + r;
        if (seen.has(k)) continue;
        seen.add(k);
        out.push({
          id: 'pp:' + k,
          source: w,
          target: r,
          data: { edgeType: 'output' },
        } as Edge);
      }
    }
  }

  return { nodes: nodes.filter((n) => n.type === 'process'), edges: out };
}

// The dual of collapseStores: the STORE-ONLY graph. Drop process nodes; for every
// process, connect each store it READS to each store it WRITES (data flows
// read-store -> process -> write-store). Shows "which state feeds which" directly.
export function collapseProcesses(
  nodes: Node[], edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  const procIds = new Set(nodes.filter((n) => n.type === 'process').map((n) => n.id));
  const reads = new Map<string, Set<string>>();   // process -> stores it reads (inputs)
  const writes = new Map<string, Set<string>>();  // process -> stores it writes (outputs)

  for (const e of edges) {
    const kind = (e.data as { edgeType?: string } | undefined)?.edgeType;
    if (kind === 'input' && procIds.has(e.target)) {
      addTo(reads, e.target, e.source);             // store -> proc (read)
    } else if (kind === 'output' && procIds.has(e.source)) {
      addTo(writes, e.source, e.target);            // proc -> store (write)
    } else if (kind === 'bidirectional') {
      const store = procIds.has(e.source) ? e.target : procIds.has(e.target) ? e.source : null;
      const proc = procIds.has(e.source) ? e.source : procIds.has(e.target) ? e.target : null;
      if (store && proc) { addTo(reads, proc, store); addTo(writes, proc, store); }
    }
  }

  const out: Edge[] = [];
  const seen = new Set<string>();
  for (const proc of new Set<string>([...reads.keys(), ...writes.keys()])) {
    const rs = reads.get(proc);
    const ws = writes.get(proc);
    if (!rs || !ws) continue;
    for (const r of rs) {
      for (const w of ws) {
        if (r === w) continue;
        const k = r + '' + w;
        if (seen.has(k)) continue;
        seen.add(k);
        out.push({
          id: 'ss:' + k,
          source: r,
          target: w,
          data: { edgeType: 'output' },
        } as Edge);
      }
    }
  }

  return { nodes: nodes.filter((n) => n.type !== 'process'), edges: out };
}

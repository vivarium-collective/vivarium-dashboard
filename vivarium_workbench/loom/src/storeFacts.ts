// src/storeFacts.ts — facts about a store derived from the wire graph.
//
// The store-side counterpart of the process contract: a process declares
// what it does with a port, and a store can report who touches it. Both
// come from data already in the document.

import type { Edge } from '@xyflow/react';

export interface StoreFacts {
  /** Processes that read this store (store -> process, edgeType 'input'). */
  readers: string[];
  /** Processes that write this store (process -> store, edgeType 'output'). */
  writers: string[];
}

export function readersAndWriters(storeId: string, edges: Edge[]): StoreFacts {
  const readers = new Set<string>();
  const writers = new Set<string>();
  for (const e of edges) {
    const kind = (e.data as { edgeType?: string } | undefined)?.edgeType;
    if (kind === 'input' && e.source === storeId) readers.add(e.target);
    else if (kind === 'output' && e.target === storeId) writers.add(e.source);
  }
  return { readers: [...readers].sort(), writers: [...writers].sort() };
}

/** The store endpoint of a wire edge (null for place / unknown edges).
 *  Input wires flow store→process, so the store is the source; output wires
 *  flow process→store, so the store is the target. */
export function wireStoreEndpoint(edge: Edge): string | null {
  const kind = (edge.data as { edgeType?: string } | undefined)?.edgeType;
  if (kind === 'input') return edge.source;
  if (kind === 'output') return edge.target;
  return null;
}

/**
 * Stores that are "hubs": wired to by at least `hubFraction` of the processes
 * that touch any store. A hub (`bulk`, `listeners`, `timestep`, …) is the
 * least-informative wire target — nearly everything reads it — so hierarchy
 * mode hides its fan by default.
 *
 * Reuses affinity.ts's hub cutoff exactly: `Math.max(3, Math.round(hubFraction
 * * n))`, where `n` is the number of distinct processes seen in the wire graph.
 * The `Math.max(3, …)` floor keeps a tiny graph (e.g. the unit-test fixtures)
 * from ever forming a hub, which is what preserves the identity-passthrough
 * guarantee there. Deterministic and O(edges).
 */
export function hubStoreIds(edges: Edge[], hubFraction = 0.30): Set<string> {
  const procsByStore = new Map<string, Set<string>>();
  const allProcs = new Set<string>();
  for (const e of edges) {
    const kind = (e.data as { edgeType?: string } | undefined)?.edgeType;
    let storeId: string;
    let procId: string;
    if (kind === 'input') { storeId = e.source; procId = e.target; }
    else if (kind === 'output') { storeId = e.target; procId = e.source; }
    else continue;
    allProcs.add(procId);
    let set = procsByStore.get(storeId);
    if (!set) { set = new Set(); procsByStore.set(storeId, set); }
    set.add(procId);
  }
  const n = allProcs.size;
  const hubs = new Set<string>();
  if (n === 0) return hubs;
  const hubCut = Math.max(3, Math.round(hubFraction * n));
  for (const [store, procs] of procsByStore) {
    if (procs.size >= hubCut) hubs.add(store);
  }
  return hubs;
}

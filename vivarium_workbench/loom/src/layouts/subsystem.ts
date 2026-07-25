// src/layouts/subsystem.ts — alternative rail groupings to the connection
// affinity in affinity.ts.
//
//   subsystem — biological function, inferred from the process-name family
//               (v2ecoli's names are very regular: ecoli-transcript-*,
//               ecoli-polypeptide-* = translation, ecoli-chromosome-* =
//               replication, …). The most navigable lens for a biologist.
//   location  — the composite's own nesting: which containing store/agent a
//               process lives under. Flat for a single cell, meaningful for
//               colonies (agents.0 / agents.1 / …).
//
// Both return the same `Cluster` shape affinity.clusterProcesses does, so the
// rail treats every axis uniformly. Pure: no React, no DOM.

import type { Node } from '@xyflow/react';
import type { Cluster } from './affinity';

export type GroupAxis = 'subsystem' | 'connection' | 'location';

/** Ordered subsystem rules — FIRST match wins, so list specific before generic
 *  (e.g. `rna-degradation` must beat a bare `rna`). Patterns test the lowercased
 *  process label. The order here is also the display order of the groups. */
const SUBSYSTEMS: { label: string; test: RegExp }[] = [
  { label: 'Replication & division', test: /chromosom|replicat|replisome|dnaa|oric|mark_d_period|d[_-]?period|\bdivision\b|divide/ },
  { label: 'Transcription',          test: /transcript|\brnap\b|rna[-_]?polymerase/ },
  { label: 'RNA processing & decay', test: /rna[-_](degrad|matur|decay|process)|rnase/ },
  { label: 'Translation',            test: /polypeptide|ribosom|translation|\btrna\b|elongation[-_]factor/ },
  { label: 'Protein turnover',       test: /protein[-_]degrad|proteolysis|protease|complexation|complex[-_]formation/ },
  { label: 'Gene regulation',        test: /tf[-_](un)?binding|transcription[-_]factor|two[-_]component|equilibrium/ },
  { label: 'Stringent response',     test: /ppgpp|\brela\b|\bspot\b|stringent/ },
  { label: 'Metabolism',             test: /metabol|metabolic|\bflux\b|\bfba\b/ },
  { label: 'Growth & shape',         test: /\bmass\b|\bshape\b|growth|volume|surface[-_]area/ },
  { label: 'Observation',            test: /deriver|counts|listener|emitter|\bviz\b/ },
];
const OTHER = 'Other';

/** The biological subsystem a process belongs to, by its name. */
export function subsystemOf(label: string): string {
  const n = (label || '').toLowerCase();
  for (const s of SUBSYSTEMS) if (s.test.test(n)) return s.label;
  return OTHER;
}

/** Sort key so groups display in SUBSYSTEMS order, with Other last. */
const subsystemOrder = new Map<string, number>(SUBSYSTEMS.map((s, i) => [s.label, i]));

function toClusters(
  groups: Map<string, string[]>,
  order: (key: string) => number,
): Cluster[] {
  return [...groups.entries()]
    .filter(([, ids]) => ids.length > 0)
    .map(([key, ids]) => ({ key, label: key, processIds: [...ids].sort() }))
    .sort((a, b) => (order(a.key) - order(b.key)) || a.key.localeCompare(b.key));
}

/** Group every process by biological subsystem. Every process is placed. */
export function subsystemClusters(nodes: Node[]): Cluster[] {
  const groups = new Map<string, string[]>();
  for (const node of nodes) {
    if (node.type !== 'process') continue;
    const key = subsystemOf(String((node.data as { label?: unknown })?.label ?? ''));
    const list = groups.get(key);
    if (list) list.push(node.id); else groups.set(key, [node.id]);
  }
  return toClusters(groups, (k) => subsystemOrder.get(k) ?? (k === OTHER ? 998 : 999));
}

/** Group every process by its containing composite path (the store it lives
 *  under). `<root>` for a top-level process. Ordered biggest group first. */
export function locationClusters(nodes: Node[]): Cluster[] {
  const groups = new Map<string, string[]>();
  const size = new Map<string, number>();
  for (const node of nodes) {
    if (node.type !== 'process') continue;
    const path = (node.data as { path?: unknown })?.path;
    const parent = Array.isArray(path) && path.length > 1
      ? (path as string[]).slice(0, -1).join('.')
      : '<root>';
    const list = groups.get(parent);
    if (list) list.push(node.id); else groups.set(parent, [node.id]);
  }
  for (const [k, ids] of groups) size.set(k, ids.length);
  // Bigger groups first, then lexical; the negative size makes larger sort earlier.
  return toClusters(groups, (k) => -(size.get(k) ?? 0));
}

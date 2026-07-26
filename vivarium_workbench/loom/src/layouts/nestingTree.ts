// src/layouts/nestingTree.ts — build a CONTAINMENT tree of the process
// inventory for the Processes panel. Instead of grouping by an abstract axis
// (subsystem / connection / location), this groups every process by WHERE it is
// nested — the composite the way it's actually built (colony → cells → a_0 →
// ecoli → transcription…). Composite Processes are flagged so the panel can
// lazily reveal their inner processes via fetchInnerComposite, "all the way
// down". Uncategorized processes are flagged so newly-added ones stand out.

import type { Node } from '@xyflow/react';
import { isUncategorizedProcess } from './subsystem';

export interface TreeNode {
  /** Stable id for React keys + expand/collapse state. */
  key: string;
  label: string;
  /** group = a store container (cells, a_0); process/step = a leaf. */
  kind: 'group' | 'process' | 'step';
  /** React Flow node id — present for on-canvas leaves (the current composite),
   *  absent for lazily-loaded inner leaves (which drill instead of focus). */
  nodeId?: string;
  /** Full store path from the composite root. */
  path: string[];
  /** A Composite Process — its inner model is itself a composite, so it can be
   *  expanded to reveal its own processes (lazy fetch). */
  isComposite?: boolean;
  /** Not classified into any subsystem — surfaced as "uncategorized". */
  isOrphan?: boolean;
  children: TreeNode[];
  /** Total process/step leaves at or under this node (excludes not-yet-loaded
   *  inner composites). */
  processCount: number;
}

// Meta / non-store keys that never appear in a bigraph store path.
const SKIP_KEYS = new Set(['instance', 'config', 'inputs', 'outputs', 'interface', 'wires']);

function labelOf(n: Node): string {
  return String((n.data as { label?: unknown })?.label ?? n.id);
}

function rollupCounts(t: TreeNode): number {
  if (t.kind !== 'group') return 1;
  t.processCount = t.children.reduce((s, c) => s + rollupCounts(c), 0);
  return t.processCount;
}

/** Insert a leaf at `path` under `root`, creating group ancestors as needed. */
function insertLeaf(
  root: TreeNode,
  byKey: Map<string, TreeNode>,
  path: string[],
  leaf: TreeNode,
): void {
  let parent = root;
  for (let i = 0; i < path.length - 1; i++) {
    const segPath = path.slice(0, i + 1);
    const k = 'g:' + segPath.join('/');
    let g = byKey.get(k);
    if (!g) {
      g = { key: k, label: segPath[i], kind: 'group', path: segPath, children: [], processCount: 0 };
      byKey.set(k, g);
      parent.children.push(g);
    }
    parent = g;
  }
  parent.children.push(leaf);
}

/** Build the containment tree from the flat React Flow node list (the CURRENT
 *  composite level). Leaves carry `nodeId` so the panel keeps full canvas
 *  affordances (focus / show-hide / keep-open). */
export function buildNestingTree(nodes: Node[]): TreeNode[] {
  const root: TreeNode = { key: '', label: '', kind: 'group', path: [], children: [], processCount: 0 };
  const byKey = new Map<string, TreeNode>([['', root]]);

  for (const n of nodes) {
    if (n.type !== 'process' && n.type !== 'step') continue;
    const data = n.data as { path?: unknown; isCompositeProcess?: unknown };
    const label = labelOf(n);
    const path = Array.isArray(data?.path) && data.path.length
      ? (data.path as string[])
      : [label];
    insertLeaf(root, byKey, path, {
      key: path.join('/') + '::' + n.id,
      label,
      kind: n.type === 'step' ? 'step' : 'process',
      nodeId: n.id,
      path,
      isComposite: data?.isCompositeProcess === true,
      isOrphan: isUncategorizedProcess(label),
      children: [],
      processCount: 1,
    });
  }
  root.children.forEach(rollupCounts);
  return root.children;
}

/** Build a subtree from a RAW bigraph state dict (an inner composite fetched on
 *  demand). Leaves have no `nodeId` — they aren't on the current canvas; the
 *  panel makes them drill into their containing composite instead. */
export function buildTreeFromState(state: unknown): TreeNode[] {
  const root: TreeNode = { key: '', label: '', kind: 'group', path: [], children: [], processCount: 0 };
  const byKey = new Map<string, TreeNode>([['', root]]);

  const walk = (node: unknown, prefix: string[]): void => {
    if (!node || typeof node !== 'object' || Array.isArray(node)) return;
    const obj = node as Record<string, unknown>;
    const t = obj._type;
    if (t === 'process' || t === 'step') {
      const label = prefix[prefix.length - 1] ?? '?';
      insertLeaf(root, byKey, prefix, {
        key: 'inner:' + prefix.join('/'),
        label,
        kind: t === 'step' ? 'step' : 'process',
        path: prefix,
        isComposite: obj.is_composite_process === true,
        isOrphan: isUncategorizedProcess(label),
        children: [],
        processCount: 1,
      });
      return; // a process's own sub-keys (config, instance…) are not stores
    }
    for (const [k, v] of Object.entries(obj)) {
      if (k.startsWith('_') || SKIP_KEYS.has(k)) continue;
      walk(v, [...prefix, k]);
    }
  };
  walk(state, []);
  root.children.forEach(rollupCounts);
  return root.children;
}

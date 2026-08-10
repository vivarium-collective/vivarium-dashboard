// src/collapseRedundant.ts — collapse topologically-identical repeated processes.
//
// Array-generated composites spawn one process per grid cell / element:
// `dFBA[0,0]`, `dFBA[1,0]`, … or `monod_kinetics[i,j]`. They share the same
// process type and the same port structure and differ only by index. When the
// "Collapse repeated processes" option is on we show ONE representative
// `dFBA[*]` node carrying a count of how many it stands for, and redirect +
// de-duplicate their wires (so N identical wires into a shared hub become one).
//
// Only INDEXED nodes (`name[...]`) are eligible, so two unrelated single
// processes that happen to share a type are never merged.

type AnyNode = { id: string; type?: string; data?: any };
type AnyEdge = {
  id: string; source: string; target: string;
  sourceHandle?: string | null; targetHandle?: string | null;
  label?: string; data?: any;
};

const INDEXED = /^(.+?)\s*\[[^\]]*\]\s*$/; // "dFBA[0,0]" → base "dFBA"

/** Base name of an array element, or null if the label is not `name[...]`. */
function baseName(label: unknown): string | null {
  if (typeof label !== 'string') return null;
  const m = INDEXED.exec(label);
  return m ? m[1].trim() : null;
}

/** Topology signature: process type + sorted port sets + array base name. */
function signature(n: AnyNode): string {
  const d = n.data ?? {};
  const inP = [...(d.inputPorts ?? [])].sort().join(',');
  const outP = [...(d.outputPorts ?? [])].sort().join(',');
  return `${d.processType ?? ''}|${inP}|${outP}|${baseName(d.label)}`;
}

export function collapseRedundantProcesses(
  nodes: AnyNode[], edges: AnyEdge[],
): { nodes: AnyNode[]; edges: AnyEdge[] } {
  // Group indexed process nodes by topology signature.
  const groups = new Map<string, AnyNode[]>();
  for (const n of nodes) {
    if (n.type !== 'process') continue;
    if (!baseName(n.data?.label)) continue;
    const key = signature(n);
    const g = groups.get(key);
    if (g) g.push(n); else groups.set(key, [n]);
  }

  const remap = new Map<string, string>();      // dropped member id → rep id
  const count = new Map<string, number>();       // rep id → members collapsed
  const relabel = new Map<string, string>();     // rep id → "base[*]"
  for (const members of groups.values()) {
    if (members.length < 2) continue;
    const rep = members[0];
    const base = baseName(rep.data?.label)!;
    count.set(rep.id, members.length);
    relabel.set(rep.id, `${base}[*]`);
    for (let i = 1; i < members.length; i++) remap.set(members[i].id, rep.id);
  }
  if (remap.size === 0) return { nodes, edges };

  const outNodes = nodes
    .filter((n) => !remap.has(n.id))            // drop the non-representative members
    .map((n) => count.has(n.id)
      ? { ...n, data: { ...n.data, label: relabel.get(n.id), _collapsedCount: count.get(n.id) } }
      : n);

  // Redirect edges onto representatives, then de-dupe identical wires.
  const seen = new Set<string>();
  const outEdges: AnyEdge[] = [];
  for (const e of edges) {
    const source = remap.get(e.source) ?? e.source;
    const target = remap.get(e.target) ?? e.target;
    if (source === target) continue;            // wire that became a self-loop
    const port = (e.data?.port ?? e.label ?? '');
    const key = `${source}|${target}|${e.sourceHandle ?? ''}|${e.targetHandle ?? ''}|${port}`;
    if (seen.has(key)) continue;
    seen.add(key);
    outEdges.push({ ...e, source, target });
  }
  return { nodes: outNodes, edges: outEdges };
}

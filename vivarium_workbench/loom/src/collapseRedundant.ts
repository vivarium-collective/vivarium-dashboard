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

// ── Processes → hyperedges (the Milner-bigraph view) ─────────────────────────
// Replace every PROCESS node with a hyperedge: a small marker (rendered as a
// dashed hyperedge node) connected by dashed links to each store the process
// touched. This turns a process bigraph (processes wired to stores via ports)
// into a Milner bigraph (a link graph of hyperedges over the same nodes) — the
// place graph (store nesting) is untouched.
export function processesToHyperedges(
  nodes: AnyNode[], edges: AnyEdge[],
): { nodes: AnyNode[]; edges: AnyEdge[] } {
  const procs = nodes.filter((n) => n.type === 'process');
  if (procs.length === 0) return { nodes, edges };
  const procIds = new Set(procs.map((p) => p.id));

  const outNodes: AnyNode[] = nodes.filter((n) => n.type !== 'process');
  const outEdges: AnyEdge[] = [];
  let ei = 0;
  for (const p of procs) {
    // Stores this process was wired to (either direction), skipping other procs.
    const stores = new Set<string>();
    for (const e of edges) {
      if (e.source === p.id && !procIds.has(e.target)) stores.add(e.target);
      if (e.target === p.id && !procIds.has(e.source)) stores.add(e.source);
    }
    if (stores.size === 0) continue;
    ei += 1;
    const hid = `__hyper__${p.id}`;
    const label = typeof p.data?.label === 'string' ? p.data.label : `e${ei}`;
    outNodes.push({
      id: hid,
      type: 'store',
      data: { label, _hyperedge: true, path: [hid] },
      // seed at the process's spot so a saved layout still roughly applies.
      position: (p as any).position ?? { x: 0, y: 0 },
    } as AnyNode);
    for (const sid of stores) {
      outEdges.push({
        id: `${hid}--${sid}`,
        source: hid, target: sid,
        type: 'floating',
        sourceHandle: 'bottom-place', targetHandle: 'top-place',
        // Milner hyperedge: purple dashed link (distinct from the grey wire /
        // solid place edges).
        style: { stroke: '#a855f7', strokeDasharray: '4,4', strokeWidth: 1.6 },
        data: { edgeType: 'hyperedge' },
      } as AnyEdge);
    }
  }
  // Keep the place graph (store↔store) edges; drop the process wire edges.
  for (const e of edges) {
    if (procIds.has(e.source) || procIds.has(e.target)) continue;
    outEdges.push(e);
  }
  return { nodes: outNodes, edges: outEdges };
}

/**
 * Relax each Milner hyperedge vertex to the CENTROID of the nodes it connects,
 * so it floats naturally in the middle of its spokes instead of being pinned at
 * the collapsed process's old spot (which left the dashed links fanning
 * unnaturally out of one corner). Run on POST-layout positions. Nodes the user
 * pinned (a saved position) are left in place; everything else settles to the
 * average center of its connected ports. Returns a new array.
 */
export function relaxHyperedgePositions(
  nodes: AnyNode[], edges: AnyEdge[], pinned?: Set<string>,
): AnyNode[] {
  const byId = new Map<string, any>(nodes.map((n) => [n.id, n]));
  const DEF = { w: 130, h: 74 }; // approx store-card size, for centering
  const centerOf = (n: any) => {
    const w = n?.width ?? DEF.w, h = n?.height ?? DEF.h;
    return { x: (n.position?.x ?? 0) + w / 2, y: (n.position?.y ?? 0) + h / 2 };
  };
  return nodes.map((n) => {
    if (!(n.data as any)?._hyperedge || pinned?.has(n.id)) return n;
    let sx = 0, sy = 0, c = 0;
    for (const e of edges) {
      const other = e.source === n.id ? e.target : e.target === n.id ? e.source : null;
      const t = other ? byId.get(other) : undefined;
      if (!t?.position) continue;
      const ctr = centerOf(t);
      sx += ctr.x; sy += ctr.y; c += 1;
    }
    if (!c) return n;
    // Place the (tiny) vertex AT the centroid of the connected ports' centers.
    return { ...n, position: { x: sx / c, y: sy / c } };
  });
}

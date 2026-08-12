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

const INDEXED = /^(.+?)\s*\[[^\]]*\]\s*$/;      // "dFBA[0,0]" → base "dFBA"
const GENERATED = /^(.+?)_[0-9a-f]{4,}$/i;       // "p_4bd003" → base "p" (auto-id hash)

/** Base + collapsed wildcard label for a repeated process, or null if the label
 *  is neither an array element (`name[...]`) nor an auto-generated id
 *  (`prefix_<hexhash>`, e.g. a per-particle composite process p_4bd003). */
function baseInfo(label: unknown): { base: string; wildcard: string } | null {
  if (typeof label !== 'string') return null;
  let m = INDEXED.exec(label);
  if (m) { const b = m[1].trim(); return { base: b, wildcard: `${b}[*]` }; }
  m = GENERATED.exec(label);
  if (m) { const b = m[1].trim(); return { base: b, wildcard: `${b}_*` }; }
  return null;
}

/** Topology signature: process type + sorted port sets + repeated-node base name. */
function signature(n: AnyNode): string {
  const d = n.data ?? {};
  const inP = [...(d.inputPorts ?? [])].sort().join(',');
  const outP = [...(d.outputPorts ?? [])].sort().join(',');
  return `${d.processType ?? ''}|${inP}|${outP}|${baseInfo(d.label)?.base ?? ''}`;
}

export function collapseRedundantProcesses(
  nodes: AnyNode[], edges: AnyEdge[],
): { nodes: AnyNode[]; edges: AnyEdge[] } {
  // Group indexed process nodes by topology signature.
  const groups = new Map<string, AnyNode[]>();
  for (const n of nodes) {
    if (n.type !== 'process') continue;
    if (!baseInfo(n.data?.label)) continue;
    const key = signature(n);
    const g = groups.get(key);
    if (g) g.push(n); else groups.set(key, [n]);
  }

  const remap = new Map<string, string>();      // dropped member id → rep id
  const count = new Map<string, number>();       // rep id → members collapsed
  const relabel = new Map<string, string>();     // rep id → "base[*]" / "base_*"
  for (const members of groups.values()) {
    if (members.length < 2) continue;
    const rep = members[0];
    count.set(rep.id, members.length);
    relabel.set(rep.id, baseInfo(rep.data?.label)!.wildcard);
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

// ── Collapse redundant sibling STORES (the place-graph dual) ─────────────────
// A `map`-typed store spawns one child per element: `particle_1`, `particle_2`,
// … each with the SAME subtree shape ({id, position, mass}) and differing only
// by value. This collapses such sibling groups to ONE representative `base_*`
// store carrying a count, dropping the other siblings AND their whole subtrees
// (stores nest — a place graph — so a dropped sibling takes its descendants with
// it), then redirects + de-dupes any wires into the dropped subtrees onto the
// representative's matching descendant. The store dual of the process collapse.

/** Structural signature of a store subtree — child KEYS + nesting, NOT values
 *  (siblings differ only by value, so values must be excluded). */
function subtreeSig(id: string, kidsOf: Map<string, AnyNode[]>): string {
  const kids = kidsOf.get(id) ?? [];
  if (kids.length === 0) return 'L';
  return '{' + kids
    .map((k) => `${k.data?.label}:${subtreeSig(k.id, kidsOf)}`)
    .sort()
    .join(',') + '}';
}

/** Common base for a sibling group: shared prefix with trailing digits/separators
 *  stripped (`particle_1`,`particle_2` → `particle`); falls back to the singular
 *  of the parent's label (`particles` → `particle`) when the keys don't share a
 *  usable prefix (e.g. random ids). */
function siblingBase(members: AnyNode[], parentLabel: string): string {
  const labels = members.map((m) => String(m.data?.label ?? ''));
  let pre = labels[0] ?? '';
  for (const l of labels) { while (pre && !l.startsWith(pre)) pre = pre.slice(0, -1); }
  pre = pre.replace(/[_\-\s\d]+$/, '');
  if (pre.length >= 2) return pre;
  return parentLabel.replace(/s$/, '') || 'item';
}

export function collapseRedundantStores(
  nodes: AnyNode[], edges: AnyEdge[],
): { nodes: AnyNode[]; edges: AnyEdge[] } {
  const kidsOf = new Map<string, AnyNode[]>();   // parent id → child store nodes
  const parentOf = new Map<string, string>();     // child id → parent id
  for (const e of edges) {
    if (e.data?.edgeType !== 'place') continue;
    (kidsOf.get(e.source) ?? kidsOf.set(e.source, []).get(e.source)!).push(
      nodes.find((n) => n.id === e.target) as AnyNode);
    parentOf.set(e.target, e.source);
  }
  // Group each parent's children by (subtree signature) — a group of ≥2 with a
  // non-leaf shape is a redundant sibling set. (Leaves like id/position/mass are
  // distinct fields, never collapsed.)
  const nodeById = new Map<string, AnyNode>(nodes.map((n) => [n.id, n]));
  const dropIds = new Set<string>();              // nodes removed entirely
  const remap = new Map<string, string>();        // dropped id → rep-equivalent id
  const relabel = new Map<string, string>();      // rep id → "base_*"
  const count = new Map<string, number>();

  for (const [parent, rawKids] of kidsOf) {
    const kids = rawKids.filter(Boolean);
    const groups = new Map<string, AnyNode[]>();
    for (const k of kids) {
      const sig = subtreeSig(k.id, kidsOf);
      if (sig === 'L') continue;                  // scalar leaf — not a subtree
      (groups.get(sig) ?? groups.set(sig, []).get(sig)!).push(k);
    }
    for (const members of groups.values()) {
      if (members.length < 2) continue;
      const rep = members[0];
      const base = siblingBase(members, String(nodeById.get(parent)?.data?.label ?? ''));
      relabel.set(rep.id, `${base}_*`);
      count.set(rep.id, members.length);
      const repPath: string[] = (rep.data?.path ?? rep.id.split('.')) as string[];
      for (let i = 1; i < members.length; i++) {
        const m = members[i];
        const mPath: string[] = (m.data?.path ?? m.id.split('.')) as string[];
        // Map the whole dropped subtree onto the rep's matching descendants.
        for (const n of nodes) {
          const p: string[] = (n.data?.path ?? n.id.split('.')) as string[];
          if (p.length < mPath.length) continue;
          if (mPath.every((seg, j) => p[j] === seg)) {
            dropIds.add(n.id);
            remap.set(n.id, [...repPath, ...p.slice(mPath.length)].join('.'));
          }
        }
      }
    }
  }
  if (dropIds.size === 0) return { nodes, edges };

  const outNodes = nodes
    .filter((n) => !dropIds.has(n.id))
    .map((n) => relabel.has(n.id)
      ? { ...n, data: { ...n.data, label: relabel.get(n.id), _collapsedCount: count.get(n.id) } }
      : n);

  const seen = new Set<string>();
  const outEdges: AnyEdge[] = [];
  for (const e of edges) {
    const source = remap.get(e.source) ?? e.source;
    const target = remap.get(e.target) ?? e.target;
    if (source === target) continue;              // collapsed into a self-loop
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
    // Start at the centroid of the connected ports' centers.
    let vx = sx / c, vy = sy / c;
    // Keep the (tiny) vertex OUT of any node box — if the centroid lands inside a
    // node, push it just past that node's nearest edge, so its spokes emanate from
    // open space instead of from inside a card.
    const NEAR = 12, MG = 30;  // treat "within NEAR of a node edge" as overlapping
    for (const mn of nodes) {
      const m = mn as any;
      if (m.data?._hyperedge || !m.position) continue;
      const w = m.width ?? DEF.w, h = m.height ?? DEF.h;
      const x0 = m.position.x - NEAR, y0 = m.position.y - NEAR;
      const x1 = m.position.x + w + NEAR, y1 = m.position.y + h + NEAR;
      if (vx > x0 && vx < x1 && vy > y0 && vy < y1) {
        // push out past the nearest inflated edge (so the vertex clears the card)
        const dl = vx - x0, dr = x1 - vx, dt = vy - y0, db = y1 - vy;
        const mmin = Math.min(dl, dr, dt, db);
        if (mmin === dl) vx = x0 - MG;
        else if (mmin === dr) vx = x1 + MG;
        else if (mmin === dt) vy = y0 - MG;
        else vy = y1 + MG;
        break;  // one clean nudge; avoid ping-ponging between adjacent cards
      }
    }
    return { ...n, position: { x: vx, y: vy } };
  });
}

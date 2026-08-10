// src/layout.ts — async layered layout via elkjs.
//
// Goal: preserve the inner/outer store hierarchy.
//   - "Outers above inners" → top-to-bottom flow (`direction: DOWN`).
//   - "Inners at the same level shown next to each other in a cluster"
//     → for every store with children, wrap that store AND its children in
//     a synthetic compound. ELK lays out each compound in isolation, so
//     siblings stay together; layered direction DOWN puts the parent at
//     the top and the children in a row below.
//
// Process nodes are pulled into a store's cluster too: their `data.path`
// parent is the store they conceptually live in, so they go into the
// same synthetic compound and end up rendered next to their siblings.
//
// Only PLACE edges (parent-store → child-store nesting) are fed to ELK
// as ranking hints. Wire edges (process port ↔ store) are drawn by
// React Flow based on the resulting positions but don't pull processes
// out of their natural cluster.

import ELK from "elkjs/lib/elk.bundled.js";
import type { Node, Edge } from "@xyflow/react";
import { hubStoreIds, wireStoreEndpoint } from "../storeFacts";

const elk = new ELK();

const COMMON_LAYOUT: Record<string, string> = {
  "elk.algorithm": "layered",
  "elk.direction": "DOWN",
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
  "elk.layered.spacing.nodeNodeBetweenLayers": "200",
  "elk.spacing.nodeNode": "55",
  "elk.padding": "[top=20,left=20,bottom=20,right=20]",
};

// Tightened options for the tiered process-through-ELK path (Change 3). Now
// that hub wires no longer clutter the graph, layers can sit much closer
// (200 → 90); BRANDES_KOEPF lines nodes up along the flow axis (the "aligned"
// read) and LEFT postCompaction squeezes out slack for a compact baseline.
// The untiered default path (layout.test.ts) keeps COMMON_LAYOUT byte-for-byte.
const TIGHT_LAYOUT: Record<string, string> = {
  "elk.algorithm": "layered",
  "elk.direction": "DOWN",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
  "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
  "elk.layered.spacing.nodeNodeBetweenLayers": "90",
  "elk.layered.compaction.postCompaction.strategy": "LEFT",
  "elk.spacing.nodeNode": "45",
  "elk.padding": "[top=20,left=20,bottom=20,right=20]",
};

/** Options for the current run: tightened when laying processes out through
 *  ELK, else the original loose spacing so the default path is unchanged. */
export interface LayoutOpts {
  /** Route process nodes through ELK (near their non-hub stores) instead of the
   *  hand-rolled trailing grid. Gated so the untiered default path is untouched. */
  layoutProcesses?: boolean;
}

function nodeSize(n: Node): { width: number; height: number } {
  // A tier-aware caller (hierarchyMode.run) stamps a per-node size hint on
  // `data._elkW`/`_elkH` so ELK reserves room for the card at the current
  // semantic-zoom tier. When absent — the untiered default path, exercised by
  // layout.test.ts — fall back to the original fixed sizes so `applyLayout`'s
  // behavior is unchanged.
  const d = n.data as { _elkW?: unknown; _elkH?: unknown } | undefined;
  if (typeof d?._elkW === "number" && typeof d?._elkH === "number") {
    return { width: d._elkW, height: d._elkH };
  }
  if (n.type === "process") return { width: 140, height: 60 };
  return { width: 80, height: 80 };  // store circle
}

function parentPathKey(n: Node): string | null {
  const path: unknown = (n.data as { path?: unknown })?.path;
  if (!Array.isArray(path) || path.length <= 1) return null;
  return (path as string[]).slice(0, -1).join(".");
}

function selfPathKey(n: Node): string | null {
  const path: unknown = (n.data as { path?: unknown })?.path;
  if (!Array.isArray(path) || path.length === 0) return null;
  return (path as string[]).join(".");
}

export async function applyLayout(
  nodes: Node[],
  edges: Edge[],
  opts: LayoutOpts = {},
): Promise<Node[]> {
  if (nodes.length === 0) return [];

  // Tiered callers (hierarchyMode.run) opt into routing processes through ELK
  // and the tightened spacing; the untiered default path (layout.test.ts) keeps
  // the loose COMMON_LAYOUT and the hand-rolled trailing grid, byte-for-byte.
  const layoutProcesses = opts.layoutProcesses === true;
  const LAYOUT = layoutProcesses ? TIGHT_LAYOUT : COMMON_LAYOUT;

  // Index nodes and the store nodes by their path-key (so we can find a
  // node's compound parent by name).
  const byId = new Map<string, Node>();
  const storeByPath = new Map<string, Node>();
  for (const n of nodes) {
    byId.set(n.id, n);
    if (n.type === "store") {
      const pk = selfPathKey(n);
      if (pk) storeByPath.set(pk, n);
    }
  }

  // For every store, find its compound parent — the visible store node whose
  // own path matches this node's parent-path. Falls back to ROOT (top-level)
  // when no such store is visible (e.g. its container is collapsed).
  const ROOT = "__root__";
  const compoundParent = new Map<string, string>();
  const childrenByParent = new Map<string, string[]>([[ROOT, []]]);
  for (const n of nodes) {
    // Stores build the hierarchy; processes are attached below once we know
    // which store each one belongs near (default path leaves them for the grid).
    if (n.type === "process") continue;
    const pk = parentPathKey(n);
    let parentId: string = ROOT;
    if (pk) {
      const parentStore = storeByPath.get(pk);
      if (parentStore) parentId = parentStore.id;
    }
    compoundParent.set(n.id, parentId);
    if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, []);
    childrenByParent.get(parentId)!.push(n.id);
  }

  // Processes that ELK will NOT place (only hub wires, or no wires at all) —
  // laid out in a compact trailing grid after ELK. Populated in the tiered path.
  const trailingProcs: Node[] = [];
  if (layoutProcesses) {
    // Attach each process as a child of the (non-hub) store it wires to most,
    // so ELK places it in a layered rank directly under that store — near the
    // store, non-overlapping. Hub wires are excluded so hub stores don't drag
    // every process into one rank (and to keep the ELK graph small).
    const hubs = hubStoreIds(edges);
    const tally = new Map<string, Map<string, number>>();  // procId -> store -> count
    for (const e of edges) {
      const store = wireStoreEndpoint(e);
      if (store == null || hubs.has(store)) continue;       // place / hub wires
      const proc = e.source === store ? e.target : e.source;
      const byStore = tally.get(proc) ?? new Map<string, number>();
      byStore.set(store, (byStore.get(store) ?? 0) + 1);
      tally.set(proc, byStore);
    }
    for (const n of nodes) {
      if (n.type !== "process") continue;
      const byStore = tally.get(n.id);
      // Dominant non-hub store: most wires, ties broken lexically for stability.
      let best: string | null = null;
      let bestCount = 0;
      for (const [store, count] of byStore ?? []) {
        if (!byId.has(store)) continue;                     // store not visible
        if (count > bestCount || (count === bestCount && (best === null || store < best))) {
          best = store; bestCount = count;
        }
      }
      if (best === null) { trailingProcs.push(n); continue; }
      compoundParent.set(n.id, best);
      if (!childrenByParent.has(best)) childrenByParent.set(best, []);
      childrenByParent.get(best)!.push(n.id);
    }
  }

  // Build the ELK tree. Stores with children get wrapped in a synthetic
  // compound whose first child is the store itself (rendered as a real
  // node) and whose remaining children are recursive compounds for the
  // store's own children. Direction DOWN places the store at the top
  // and its children in a row below.
  function buildElkChildren(parentId: string): unknown[] {
    const ids = childrenByParent.get(parentId) ?? [];
    return ids.map((id) => buildElkNodeFor(id));
  }
  function buildElkNodeFor(id: string): unknown {
    const node = byId.get(id);
    if (!node) return { id, width: 0, height: 0 };
    const grandChildren = childrenByParent.get(id) ?? [];
    if (grandChildren.length === 0) {
      // Leaf
      return {
        id,
        ...nodeSize(node),
      };
    }
    // Compound: synthetic wrapper containing this node + recursive
    // sub-compounds for its children.
    return {
      id: `wrap:${id}`,
      layoutOptions: LAYOUT,
      children: [
        { id, ...nodeSize(node) },
        ...buildElkChildren(id),
      ],
      // Synthetic internal edges from the parent to each child push the
      // parent to the top of the compound under direction: DOWN.
      edges: grandChildren.map((cid) => {
        const childTarget = (childrenByParent.get(cid) ?? []).length > 0
          ? `wrap:${cid}` : cid;
        return {
          id: `internal:${id}->${childTarget}`,
          sources: [id],
          targets: [childTarget],
        };
      }),
    };
  }

  // Top-level place edges between top-level stores (rare but possible).
  const topLevelChildIds = childrenByParent.get(ROOT) ?? [];
  const topLevelStoreIds = new Set(topLevelChildIds);
  const topLevelEdges = edges
    .filter((e) => (e.data as { edgeType?: string } | undefined)?.edgeType === "place")
    .filter((e) => topLevelStoreIds.has(e.source) && topLevelStoreIds.has(e.target))
    .map((e) => {
      const targetWrap = (childrenByParent.get(e.target) ?? []).length > 0
        ? `wrap:${e.target}` : e.target;
      return {
        id: e.id,
        sources: [e.source],
        targets: [targetWrap],
      };
    });

  const elkGraph = {
    id: ROOT,
    layoutOptions: LAYOUT,
    children: topLevelChildIds.map((id) => buildElkNodeFor(id)),
    edges: topLevelEdges,
  };

  const result = (await elk.layout(elkGraph as never)) as {
    children?: Array<{ id: string; x?: number; y?: number; children?: unknown[] }>;
  };

  // Flatten to absolute positions for every real node. Skip synthetic
  // "wrap:*" wrapper compounds — only real React Flow nodes need a position.
  const positions = new Map<string, { x: number; y: number }>();
  function walk(n: { id: string; x?: number; y?: number; children?: unknown[] }, parentX = 0, parentY = 0) {
    const absX = parentX + (n.x ?? 0);
    const absY = parentY + (n.y ?? 0);
    if (n.id !== ROOT && !n.id.startsWith("wrap:")) {
      positions.set(n.id, { x: absX, y: absY });
    }
    for (const c of (n.children ?? []) as Array<{ id: string; x?: number; y?: number; children?: unknown[] }>) {
      walk(c, absX, absY);
    }
  }
  walk({ id: ROOT, children: result.children });

  // Soft depth alignment (app/tiered path only — the untiered default path stays
  // byte-identical for layout.test.ts): nudge each store's Y toward the mean Y of
  // all stores at its bigraph depth, so same-depth stores gain SOME horizontal
  // alignment ACROSS clusters without snapping to strict rows. X (the cluster)
  // and the ELK-placed processes are untouched — only store Y is softly pulled.
  if (layoutProcesses) {
    const depthOf = (n: Node) => {
      const p = (n.data as { path?: unknown })?.path;
      return Array.isArray(p) ? p.length : 1;
    };
    const ysByDepth = new Map<number, number[]>();
    for (const n of nodes) {
      if (n.type !== "store") continue;
      const p = positions.get(n.id);
      if (!p) continue;
      const d = depthOf(n);
      if (!ysByDepth.has(d)) ysByDepth.set(d, []);
      ysByDepth.get(d)!.push(p.y);
    }
    const bandY = new Map<number, number>();
    for (const [d, ys] of ysByDepth) bandY.set(d, ys.reduce((a, b) => a + b, 0) / ys.length);
    const ALPHA = 0.4;  // 0 = pure clustering, 1 = strict depth rows
    for (const n of nodes) {
      if (n.type !== "store") continue;
      const p = positions.get(n.id);
      const by = bandY.get(depthOf(n));
      if (p && by != null) positions.set(n.id, { x: p.x, y: p.y + (by - p.y) * ALPHA });
    }
  }

  // Place leftover process nodes in a GRID of vertical columns to the right of
  // everything already laid out, evenly spaced. A single column of N processes
  // is ~N*110px tall; for big composites that's thousands of px and frames as an
  // unusable sliver. So wrap into columns once a column reaches ~14 rows,
  // keeping the block roughly square and easy to fit.
  //
  // Which processes land here depends on the path:
  //  - default (untiered) path: ALL processes — ELK never placed any of them.
  //  - tiered path: only the trailing set (processes with no non-hub wire —
  //    e.g. `emitter`, which touches only hubs), since the rest were attached
  //    under their dominant store above and ELK positioned them near it.
  const storePts = [...positions.values()];
  const procNodes = layoutProcesses
    ? trailingProcs
    : nodes.filter((n) => n.type === "process");
  if (storePts.length > 0 && procNodes.length > 0) {
    // H_SPACE is the gap BETWEEN process columns. Process port labels render
    // outside the box, so a tight gap let adjacent columns' port text overlap;
    // widen it substantially so columns read as clearly separated.
    //
    // The process CARD grows with the semantic-zoom tier, so the grid pitch must
    // too, or high-tier cards overlap. A tier-aware caller stamps the card's
    // footprint on `data._elkW/_elkH`; read it (all processes get the same tier
    // size in one run) and fall back to the original 140×60 when absent, keeping
    // the untiered default path byte-identical.
    const hintW = (procNodes[0].data as { _elkW?: unknown } | undefined)?._elkW;
    const PROC_W = typeof hintW === "number" ? hintW : 140;
    // Cards can now differ in height (per-port reservation), so pitch the grid by
    // the TALLEST card here, not the first, or a tall trailing card would overlap
    // the row below it.
    const PROC_H = Math.max(
      ...procNodes.map((n) => {
        const h = (n.data as { _elkH?: unknown } | undefined)?._elkH;
        return typeof h === "number" ? h : 60;
      }),
    );
    const GAP_X = 240, H_SPACE = 210, V_SPACE = 66;
    // Right edge of everything already placed. The default path only positioned
    // stores (constant 80 wide, matching the historical +80), so it stays
    // byte-identical; the tiered path also positioned processes, so measure each
    // node's real footprint to clear the widest ELK-placed card.
    const maxRight = layoutProcesses
      ? Math.max(...[...positions].map(([id, p]) => {
          const nd = byId.get(id);
          return p.x + (nd ? nodeSize(nd).width : 80);
        }))
      : Math.max(...storePts.map((p) => p.x)) + 80; // +store circle width
    const minY = Math.min(...storePts.map((p) => p.y));
    const procColX = maxRight + GAP_X;
    // Aim for a roughly-square block: rows ≈ ceil(sqrt(n)), capped to a sane band.
    const maxRows = Math.min(16, Math.max(6, Math.ceil(Math.sqrt(procNodes.length))));
    procNodes.forEach((n, i) => {
      const col = Math.floor(i / maxRows);
      const row = i % maxRows;
      positions.set(n.id, {
        x: procColX + col * (PROC_W + H_SPACE),
        y: minY + row * (PROC_H + V_SPACE),
      });
    });
  }

  return nodes.map((n) => {
    const p = positions.get(n.id);
    return p ? { ...n, position: p } : n;
  });
}

/**
 * Compact layout: tight grid, no hierarchy consideration. Synchronous
 * fallback for tiny composites or environments without async support.
 */
export function applyCompactLayout(nodes: Node[]): Node[] {
  const spacing = 100;
  const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
  return nodes.map((n, i) => ({
    ...n,
    position: {
      x: (i % cols) * spacing,
      y: Math.floor(i / cols) * spacing,
    },
  }));
}

import type { LayoutMode, LayoutResult, LayoutContext, FocusContext } from './types';
import { TIERS } from './tiers';

/**
 * Store footprint per tier. The store card grows only modestly with tier (a
 * label plus at most a value/type/wiring/emit row — see StoreNode + App.css),
 * far less than a process card. These sizes reserve enough ELK room to keep the
 * grown stores from touching without ballooning the layout.
 */
// ELK footprint reserved per store per tier. From `types` up the store card is
// content-driven (App.css) but capped at max-width 150px; these reservations
// comfortably exceed that cap so a long store name / type string can never make
// a card overlap its neighbour (ELK's nodeNode spacing adds further margin).
const STORE_ELK_SIZE: Record<string, { width: number; height: number }> = {
  glyph:    { width: 80,  height: 80 },
  ports:    { width: 100, height: 88 },
  types:    { width: 168, height: 110 },
  contract: { width: 168, height: 128 },
  full:     { width: 168, height: 150 },
};

export const hierarchyMode: LayoutMode = {
  id: 'hierarchy',
  label: 'Hierarchy',
  tiers: TIERS,
  async run(nodes: Node[], edges: Edge[], ctx: LayoutContext): Promise<LayoutResult> {
    // Size each ELK node for the current semantic-zoom tier so cards that grow
    // with zoom don't overlap. Process cards adopt the tier's card footprint
    // exactly (the CSS widths match TIERS.cardWidth/cardHeight); stores get a
    // smaller tier-scaled footprint. `nodeSize` reads these hints off
    // `data._elkW/_elkH`; without them (any untiered caller) it keeps the
    // original fixed sizes, so `applyLayout`'s default path is unchanged.
    const tier = TIERS.find((t) => t.id === ctx.tier) ?? TIERS[1];
    const storeSize = STORE_ELK_SIZE[tier.id] ?? STORE_ELK_SIZE.ports;
    // From the `types` tier up the card renders one ROW per port (plus the
    // contract math / symbols), so a many-port process (metabolism, transcript_*)
    // is far taller than the tier's base card height. Reserve that real height
    // for ELK — otherwise a tall card overflows downward past its ELK box into
    // the next layer and visually collides. `nodeSize` reads this `_elkH`, so
    // both the ELK ranks and the trailing grid space the card correctly.
    const showsPortRows = tier.id === 'types' || tier.id === 'config' || tier.id === 'contract' || tier.id === 'full';
    const PORT_ROW_H = 16;
    const processHeight = (n: Node): number => {
      if (!showsPortRows) return tier.cardHeight;
      const d = n.data as { inputPorts?: unknown; outputPorts?: unknown } | undefined;
      const nPorts = (Array.isArray(d?.inputPorts) ? d!.inputPorts.length : 0)
        + (Array.isArray(d?.outputPorts) ? d!.outputPorts.length : 0);
      return tier.cardHeight + nPorts * PORT_ROW_H;
    };
    const sized = nodes.map((n) => {
      const size = n.type === 'process'
        ? { width: tier.cardWidth, height: processHeight(n) }
        : storeSize;
      return { ...n, data: { ...n.data, _elkW: size.width, _elkH: size.height } };
    });
    // Route processes through ELK (near their non-hub stores) — the opt-in that
    // also switches on the tightened spacing. The untiered default path (no
    // opts) is left byte-identical for layout.test.ts.
    return { nodes: await applyLayout(sized, edges, { layoutProcesses: true }) };
  },

  // Hub-store wires (bulk / listeners / timestep …) are most of the ~400 edges
  // and the least informative — nearly every process touches them. Hide them by
  // default: keep place edges (the store hierarchy) and non-hub wires; drop a
  // wire whose STORE endpoint is a hub. The "Show hub wires" toggle (App state,
  // carried on the focus context) flips this off to reveal everything.
  //
  // This is STRUCTURAL, not focus-driven (see `focusReveals: false`): the set of
  // drawn edges depends only on the toggle, not on hover/selection — so App's
  // hover handlers, focus hint, and pin pruning stay off for hierarchy, exactly
  // as before this feature. The hidden fan is not lost: hub stores surface their
  // reader/writer counts on the store card (App stamps them from the full edge
  // set) so "41 read · 12 write" stands in for the wires.
  //
  // Identity-preserving: returns the INPUT array when nothing is dropped (the
  // toggle is on, or the graph is too small to have a hub — the unit fixtures),
  // so React Flow doesn't re-derive its edge store on a no-op.
  edgeVisibility(edges: Edge[], focus: FocusContext, _nodes: Node[]): Edge[] {
    if (focus.showHubWires) return edges;
    const hubs = hubStoreIds(edges);
    if (hubs.size === 0) return edges;
    const out = edges.filter((e) => {
      const store = wireStoreEndpoint(e);
      if (store == null) return true;      // place / non-wire edges: always kept
      return !hubs.has(store);             // wire kept only if its store isn't a hub
    });
    return out.length === edges.length ? edges : out;
  },

  // Hub-hiding is toggle-driven, not focus-driven — so App leaves hover
  // tracking, the focus hint, and pin pruning off for this mode.
  focusReveals: false,
};

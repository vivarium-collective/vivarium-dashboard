// layouts/incremental.ts — incremental, overlap-free placement for HISTORY
// playback (topology trajectories). When a saved-history frame ADDS place-graph
// nodes (a cell divides, the biofilm colonizes), the nodes that were already on
// screen must keep their positions and only the NEW nodes move — into free
// space, never overlapping an existing card. A full re-layout each frame both
// disturbs stable nodes and (mixed with saved/dragged positions) leaves cards
// on top of each other; this keeps the picture calm and legible as it grows.

const GAP = 28;          // clear space required between card boxes
const DEF_W = 190;       // fallback footprint when a new node isn't measured yet
const DEF_H = 130;

interface Box { x: number; y: number; w: number; h: number; }

function typeOf(n: any): string {
  return String(n?.data?.control ?? n?.data?._control ?? n?.data?._type ?? n?.type ?? '');
}

function measured(n: any): { w: number; h: number } | null {
  const w = n.width || n.measured?.width || n.data?._size?.width;
  const h = n.height || n.measured?.height || n.data?._size?.height;
  return (w && h) ? { w, h } : null;
}

/**
 * Keep every node in `fixedIds` exactly where it is; move only the other
 * (new) nodes so no two card boxes overlap. New nodes start from their
 * candidate (freshly-laid-out) position and are nudged to the nearest free
 * spot — a coarse down-then-right spiral so a crowded column spills sideways.
 * Mutates `nodes` in place.
 */
export function placeNewNodesNoOverlap(nodes: any[], fixedIds: Set<string>): void {
  // Estimate a new node's footprint from an already-measured node of the same
  // kind (topology frames add siblings — a new "cell" is sized like an old one).
  const sizeByType = new Map<string, { w: number; h: number }>();
  for (const n of nodes) {
    const m = measured(n);
    if (m) {
      const t = typeOf(n);
      if (!sizeByType.has(t)) sizeByType.set(t, m);
    }
  }
  const sizeOf = (n: any): { w: number; h: number } =>
    measured(n) ?? sizeByType.get(typeOf(n)) ?? { w: DEF_W, h: DEF_H };
  const boxOf = (n: any): Box => { const s = sizeOf(n); return { x: n.position.x, y: n.position.y, w: s.w, h: s.h }; };
  const overlap = (a: Box, b: Box): boolean =>
    !(a.x + a.w + GAP <= b.x || b.x + b.w + GAP <= a.x
      || a.y + a.h + GAP <= b.y || b.y + b.h + GAP <= a.y);

  const placed: Box[] = nodes.filter((n) => fixedIds.has(n.id)).map(boxOf);
  for (const n of nodes) {
    if (fixedIds.has(n.id)) continue;
    let b = boxOf(n);
    let tries = 0;
    while (placed.some((p) => overlap(b, p)) && tries < 600) {
      tries++;
      n.position = {
        x: n.position.x + (tries % 6 === 0 ? (b.w + GAP) : 0),
        y: n.position.y + (b.h + GAP),
      };
      b = boxOf(n);
    }
    placed.push(b);
  }
}

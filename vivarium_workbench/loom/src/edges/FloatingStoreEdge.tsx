// src/edges/FloatingStoreEdge.tsx — custom edge for process<->store wires.
//
// The process end stays pinned to its port handle (inputs left, outputs
// right). The store end floats: it attaches at the point on the store circle
// nearest that port, instead of a fixed left/right handle.
import { memo } from 'react';
import {
  BaseEdge, EdgeLabelRenderer, useInternalNode,
  type EdgeProps,
} from '@xyflow/react';
import { type Point } from './geometry';
import { abbreviateType } from '../contract';
import type { ZoomTierId } from '../layouts/types';

type RFInternalNode = NonNullable<ReturnType<typeof useInternalNode>>;

export interface EdgeLabelParts {
  port: string;
  portType?: string;
  semantic?: string;
}

/** What a wire says about itself at a given tier. Empty string means no
 *  label at all — which is also the perf path, since ~400 edges labelled
 *  at low zoom costs text layout for glyphs nobody can read. */
export function edgeLabelFor(tier: ZoomTierId, parts: EdgeLabelParts): string {
  if (tier === 'glyph') return '';
  let label = parts.port;
  if (tier === 'ports') return label;
  if (parts.portType) label += `: ${abbreviateType(parts.portType)}`;
  if ((tier === 'contract' || tier === 'full') && parts.semantic) {
    label += ` — ${parts.semantic}`;
  }
  return label;
}

/** The point on an axis-aligned box (half-width `hw`, half-height `hh` about
 *  `center`) where the ray from the center toward `toward` crosses the
 *  boundary — so a wire can attach ANYWHERE on the store's edge (whichever face
 *  is most convenient), not only its top/bottom. */
function boxAnchor(center: Point, hw: number, hh: number, toward: Point): Point {
  const dx = toward.x - center.x, dy = toward.y - center.y;
  if (dx === 0 && dy === 0) return { x: center.x + hw, y: center.y };
  const s = Math.min(hw / (Math.abs(dx) || 1e-9), hh / (Math.abs(dy) || 1e-9));
  return { x: center.x + dx * s, y: center.y + dy * s };
}

/** A point just outside `anchor` along the OUTWARD normal of the box face it
 *  sits on, so the wire enters that face perpendicular. */
function boxApproach(center: Point, hw: number, hh: number, anchor: Point, gap: number): Point {
  const dx = anchor.x - center.x, dy = anchor.y - center.y;
  if (Math.abs(dx) / hw >= Math.abs(dy) / hh) {
    return { x: anchor.x + Math.sign(dx || 1) * gap, y: anchor.y };
  }
  return { x: anchor.x, y: anchor.y + Math.sign(dy || 1) * gap };
}

/** An SVG path through `pts` with rounded corners of radius `r` — an
 *  orthogonal polyline whose bends are filleted so the wire reads as a smooth
 *  route rather than hard right angles. */
function roundedPath(pts: Point[], r: number): string {
  if (pts.length === 0) return '';
  if (pts.length === 1) return `M ${pts[0].x},${pts[0].y}`;
  let d = `M ${pts[0].x},${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const p0 = pts[i - 1], p1 = pts[i], p2 = pts[i + 1];
    const v1x = p0.x - p1.x, v1y = p0.y - p1.y;
    const v2x = p2.x - p1.x, v2y = p2.y - p1.y;
    const l1 = Math.hypot(v1x, v1y) || 1;
    const l2 = Math.hypot(v2x, v2y) || 1;
    const d1 = Math.min(r, l1 / 2), d2 = Math.min(r, l2 / 2);
    const a = { x: p1.x + (v1x / l1) * d1, y: p1.y + (v1y / l1) * d1 };
    const b = { x: p1.x + (v2x / l2) * d2, y: p1.y + (v2y / l2) * d2 };
    d += ` L ${a.x.toFixed(2)},${a.y.toFixed(2)} Q ${p1.x.toFixed(2)},${p1.y.toFixed(2)} ${b.x.toFixed(2)},${b.y.toFixed(2)}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${last.x.toFixed(2)},${last.y.toFixed(2)}`;
  return d;
}

/** Absolute center of a node from its measured box. */
function nodeCenter(n: RFInternalNode): Point {
  const p = n.internals.positionAbsolute;
  return {
    x: p.x + (n.measured.width ?? 0) / 2,
    y: p.y + (n.measured.height ?? 0) / 2,
  };
}

/**
 * Absolute position of a node's handle by id; falls back to the node center.
 *
 * `prefer` disambiguates when the SAME port name exists as both an input
 * (target handle, left) and an output (source handle, right) on one process —
 * the common case (e.g. equilibrium reads AND writes `bulk`). Without it, an
 * input wire for `bulk` would match the right-side output handle first and
 * every input wire would pile onto the process's right edge. We search the
 * preferred handle type first, then fall back to the other type, then center.
 */
function handlePoint(
  n: RFInternalNode, handleId: string | null | undefined,
  prefer: 'source' | 'target',
): Point {
  const preferred = n.internals.handleBounds?.[prefer] ?? [];
  const other = n.internals.handleBounds?.[prefer === 'source' ? 'target' : 'source'] ?? [];
  const bounds = [...preferred, ...other];
  const h = handleId ? bounds.find((b) => b.id === handleId) : undefined;
  if (!h) return nodeCenter(n);
  const p = n.internals.positionAbsolute;
  return { x: p.x + h.x + h.width / 2, y: p.y + h.y + h.height / 2 };
}

function FloatingStoreEdge({
  source, target, sourceHandleId, targetHandleId, markerEnd, style, data,
}: EdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  if (!sourceNode || !targetNode) return null;

  // edgeType 'input'  → source = store,   target = process
  // edgeType 'output' → source = process, target = store
  const storeIsSource = (data as { edgeType?: string } | undefined)?.edgeType === 'input';
  const storeNode = storeIsSource ? sourceNode : targetNode;
  const procNode = storeIsSource ? targetNode : sourceNode;
  const procHandleId = storeIsSource ? targetHandleId : sourceHandleId;

  // Process end: the exact port handle position (fixed). Inputs live on the
  // process's TARGET (left) handles, outputs on its SOURCE (right) handles —
  // resolve against the matching type so a port name shared by both doesn't
  // snap the input wire to the output handle.
  const procPoint = handlePoint(procNode, procHandleId, storeIsSource ? 'target' : 'source');

  // Store end: attaches on the store's BOX boundary (any face), not a fixed
  // handle. The exact anchor is chosen per-case below from the approach side.
  const center = nodeCenter(storeNode);
  const shw = (storeNode.measured.width ?? 0) / 2;
  const shh = (storeNode.measured.height ?? 0) / 2;
  if (shw <= 0 || shh <= 0) return null;  // not measured yet — RF re-renders when it is

  // Route AROUND the card so the wire can be tracked from its port, around the
  // process body, to its store — never diving under the rectangle. The wire
  // leaves the port perpendicular (out past the card's left edge for inputs,
  // its right edge for outputs) by EXIT_GAP.
  //
  //  • Store OUT IN FRONT of that exit → a short vertical jog reaches it (a
  //    clean L).
  //  • Store BEHIND the port (the common read+write case, where an input's
  //    store actually sits on the output side) → the wire runs out to a lane
  //    just above or below the card, travels along that lane clear of the
  //    body, and drops into the store's near face — an orthogonal C around the
  //    process, instead of a bezier that cuts under it.
  const EXIT_GAP = 24, LANE_GAP = 22, CORNER = 12;
  const pAbs = procNode.internals.positionAbsolute;
  const pw = procNode.measured.width ?? 0;
  const ph = procNode.measured.height ?? 0;
  const box = { x0: pAbs.x, y0: pAbs.y, x1: pAbs.x + pw, y1: pAbs.y + ph };
  const boxCy = (box.y0 + box.y1) / 2;
  const outX = storeIsSource ? -1 : 1;              // input exits left, output exits right
  const stub: Point = { x: procPoint.x + outX * EXIT_GAP, y: procPoint.y };
  // Is the store out in front of the exit (same side as the port), or behind
  // the card (so a straight run would cross the body)?
  const storeInFront = outX < 0 ? center.x <= box.x0 : center.x >= box.x1;
  const APPROACH = 14;

  // Waypoints, drawn process→store; reversed below for inputs so the arrow
  // marker still lands on the process port. The store end attaches on whichever
  // box face is nearest the approach (boxAnchor), entered perpendicular.
  let way: Point[];
  if (storeInFront) {
    const anchor = boxAnchor(center, shw, shh, stub);
    const ap = boxApproach(center, shw, shh, anchor, APPROACH);
    way = [procPoint, stub, ap, anchor];
  } else {
    const overTop = center.y < boxCy;
    const laneY = overTop ? box.y0 - LANE_GAP : box.y1 + LANE_GAP;
    const anchor = boxAnchor(center, shw, shh, { x: center.x, y: laneY });
    const ap = boxApproach(center, shw, shh, anchor, APPROACH);
    way = [procPoint, stub, { x: stub.x, y: laneY }, { x: ap.x, y: laneY }, ap, anchor];
  }
  const pts = storeIsSource ? [...way].reverse() : way;
  const path = roundedPath(pts, CORNER);
  const mid = pts[Math.floor(pts.length / 2)];
  const labelX = mid.x, labelY = mid.y;

  // Semantic zoom is opt-in: only process-column mode stamps `_tier` onto the
  // edge data. Absent it (hierarchy mode, or the glyph tier which App leaves
  // unstamped), draw NO label at all — no EdgeLabelRenderer node, so there is
  // genuinely no text layout to pay for when the canvas is most crowded.
  const stampedTier = (data as { _tier?: ZoomTierId } | undefined)?._tier;
  const label = stampedTier
    ? edgeLabelFor(stampedTier, {
        port: (data as { port?: string } | undefined)?.port ?? '',
        portType: (data as { _portType?: string } | undefined)?._portType,
        semantic: (data as { _semantic?: string } | undefined)?._semantic,
      })
    : '';

  // Focus highlighting: the drawn-edge seam (clusterGridEdgeVisibility) stamps
  // `_focused` on the focused process's wires and `_dim` on the rest while a
  // focus is active. Emphasize the focused set (thicker + highlight color) and
  // fade the others so the focused neighbourhood reads clearly at any zoom.
  const focused = (data as { _focused?: boolean } | undefined)?._focused === true;
  const dim = (data as { _dim?: boolean } | undefined)?._dim === true;
  const edgeClass = focused ? 'loom-edge-focused' : dim ? 'loom-edge-dim' : undefined;
  const edgeStyle = {
    ...(style as Record<string, unknown>),
    ...(focused ? { stroke: '#2563eb', strokeWidth: 2.4 } : {}),
    ...(dim ? { opacity: 0.12 } : {}),
  };

  return (
    <>
      <BaseEdge path={path} markerEnd={markerEnd} style={edgeStyle} className={edgeClass} />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="loom-edge-label nodrag nopan"
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export default memo(FloatingStoreEdge);

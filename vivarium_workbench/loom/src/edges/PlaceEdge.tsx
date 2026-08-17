// src/edges/PlaceEdge.tsx — the place (containment) edge between an outer store
// and an inner store.
//
// Rendered as an ORG-CHART ELBOW: a vertical drop from the parent's bottom, a
// horizontal run, then a vertical drop into the child's top — reading as "this
// inner store is nested inside the outer one," the way a file tree conveys
// containment.
//
// Distinguishable siblings: instead of every child of a parent sharing ONE bus
// line (which collapses their edges into a single indistinguishable bracket),
// each edge's horizontal run sits at a height that grows with the child's
// HORIZONTAL distance from the parent — so a parent's children fan into NESTED
// brackets you can trace one by one (near children bracket high, far ones low),
// with no extra crossings.
//
// Lineage spotlight: when a node is selected, App stamps `_lineage` on the place
// edges along the selected node's containment path (+ its children) and `_dim`
// on the rest, so the hierarchy around the selection pops (bold accent, raised)
// while everything else fades back.
import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, Position, type EdgeProps } from '@xyflow/react';

const PLACE_RADIUS = 12;
const LINEAGE_COLOR = '#2563eb';   // focus blue, matches the selection ring

function PlaceEdge({
  sourceX, sourceY, targetX, targetY, markerEnd, style, data,
}: EdgeProps) {
  const d = data as { _dim?: boolean; _lineage?: boolean } | undefined;
  const dim = d?._dim === true;
  const lineage = d?._lineage === true;

  // Per-sibling channel: horizontal run height grows with horizontal distance,
  // clamped to stay between the parent bottom and the child top. Falls back to
  // the plain midpoint when the child isn't clearly below (degenerate place
  // graphs) so the elbow never inverts.
  const drop = targetY - sourceY;
  let centerY: number | undefined;
  if (drop > 44) {
    const dist = Math.abs(targetX - sourceX);
    centerY = Math.max(sourceY + 16, Math.min(targetY - 16, sourceY + 20 + dist * 0.12));
  }

  const [path] = getSmoothStepPath({
    sourceX, sourceY, sourcePosition: Position.Bottom,
    targetX, targetY, targetPosition: Position.Top,
    borderRadius: PLACE_RADIUS,
    ...(centerY != null ? { centerY } : {}),
  });

  const edgeStyle: Record<string, unknown> = {
    strokeLinejoin: 'round',
    strokeLinecap: 'round',
    ...(style as Record<string, unknown>),      // convert.ts stroke #475569 / 2.6
    // Idle place edges recede a touch so dense hierarchies read calm; the
    // selected lineage overrides this with bold accent + full opacity.
    ...(lineage
      ? { stroke: LINEAGE_COLOR, strokeWidth: 3.5, opacity: 1 }
      : dim ? { opacity: 0.12 } : { opacity: 1 }),
  };
  return <BaseEdge path={path} markerEnd={markerEnd} style={edgeStyle} />;
}

export default memo(PlaceEdge);

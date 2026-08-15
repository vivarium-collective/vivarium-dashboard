// src/edges/PlaceEdge.tsx — the place (containment) edge between an outer store
// and an inner store.
//
// Rendered as an ORG-CHART ELBOW rather than a bezier: a vertical drop from the
// parent store's bottom, a horizontal run along a shared bus, then a vertical
// drop into the child's top. Row-aligned siblings share the same bus Y (the
// midpoint between the parent bottom and the child-row top that
// getSmoothStepPath picks), so their horizontals overlap into ONE clean
// bracket — reading as "these inner stores are nested inside the outer store,"
// the way a file tree or org chart conveys containment.
import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, Position, type EdgeProps } from '@xyflow/react';

// A hair of corner rounding so the bends aren't pixel-harsh, while still reading
// as crisp right angles (not the old loose bezier).
const PLACE_RADIUS = 4;

function PlaceEdge({
  sourceX, sourceY, targetX, targetY, markerEnd, style, data,
}: EdgeProps) {
  const [path] = getSmoothStepPath({
    sourceX, sourceY, sourcePosition: Position.Bottom,
    targetX, targetY, targetPosition: Position.Top,
    borderRadius: PLACE_RADIUS,
  });
  // Match the process-wire focus convention: fade place edges outside the
  // focused neighbourhood so a focused store's containment still reads.
  const dim = (data as { _dim?: boolean } | undefined)?._dim === true;
  const edgeStyle = {
    strokeLinejoin: 'round' as const,
    strokeLinecap: 'round' as const,
    ...(style as Record<string, unknown>),
    ...(dim ? { opacity: 0.12 } : {}),
  };
  return <BaseEdge path={path} markerEnd={markerEnd} style={edgeStyle} />;
}

export default memo(PlaceEdge);

// src/edges/LightWireEdge.tsx — the lightweight default edge.
//
// The force layout puts each store right next to the processes it wires, so the
// wires are SHORT. That lets the default (non-focused) fan use a cheap straight
// path drawn from the endpoint coordinates React Flow already computes from the
// handles — no `useInternalNode`, no per-render floating-circle anchor math, no
// label layout. FloatingStoreEdge (the rich, labelled, floating-anchor edge) is
// kept only for the few FOCUSED wires (App switches an edge's `type` to
// 'floating' when it is stamped `_focused`).
//
// This is the performance change: ~110 non-hub wires render as plain segments,
// so pan/zoom stays smooth, while a focused process still gets the detailed
// floating/labelled treatment.
import { memo } from 'react';
import { BaseEdge, getStraightPath, type EdgeProps } from '@xyflow/react';

function LightWireEdge({
  sourceX, sourceY, targetX, targetY, markerEnd, style, data,
}: EdgeProps) {
  const [path] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  // When a focus is active, non-focused wires are stamped `_dim` so the focused
  // neighbourhood stands out. Otherwise the wire draws in its default style.
  const dim = (data as { _dim?: boolean } | undefined)?._dim === true;
  const edgeStyle = {
    ...(style as Record<string, unknown>),
    ...(dim ? { opacity: 0.1 } : {}),
  };
  return (
    <BaseEdge
      path={path}
      markerEnd={markerEnd}
      style={edgeStyle}
      className={dim ? 'loom-edge-dim' : undefined}
    />
  );
}

export default memo(LightWireEdge);

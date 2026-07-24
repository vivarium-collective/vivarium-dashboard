// src/edges/BoundaryLabels.tsx — off-screen store name labels at the viewport
// edge, for FOCUSED wires whose store endpoint has been panned/zoomed away.
//
// Rendered as a child of <ReactFlow> so it can read the live viewport transform
// and node geometry. It contributes NO layout math of its own worth testing —
// all the segment∩viewport geometry lives in the pure `offscreenBoundaryPoint`
// helper (boundary.ts, unit-tested). This component only projects flow-space
// node centers to pane-local screen coordinates (using the store transform) and
// positions a pill at each crossing. It re-renders live on pan/zoom because it
// subscribes to the store `transform` / pane size.

import { memo, useMemo } from 'react';
import { useStore, useReactFlow, type Edge } from '@xyflow/react';
import { wireStoreEndpoint } from '../storeFacts';
import { offscreenBoundaryPoint, isInsideRect, type Rect } from './boundary';
import type { Point } from './geometry';

interface BoundaryLabelsProps {
  /** The currently-drawn edges (App's `tieredEdges`); only those stamped
   *  `_focused` are considered, so labels never clutter the default view. */
  edges: Edge[];
}

/** Pane-local screen center of a node from the live viewport transform. */
function screenCenter(
  posAbs: { x: number; y: number } | undefined,
  measured: { width?: number | null; height?: number | null } | undefined,
  fallback: number,
  transform: readonly [number, number, number],
): Point | null {
  if (!posAbs) return null;
  const [tx, ty, zoom] = transform;
  const w = measured?.width ?? fallback;
  const h = measured?.height ?? fallback;
  const cx = posAbs.x + w / 2;
  const cy = posAbs.y + h / 2;
  return { x: cx * zoom + tx, y: cy * zoom + ty };
}

function BoundaryLabelsImpl({ edges }: BoundaryLabelsProps) {
  const transform = useStore((s) => s.transform);
  const width = useStore((s) => s.width);
  const height = useStore((s) => s.height);
  const { getInternalNode, getNode, setCenter } = useReactFlow();

  const labels = useMemo(() => {
    const rect: Rect = { width, height };
    if (width <= 0 || height <= 0) return [];
    // One label per off-screen store (a store may receive several focused wires).
    const byStore = new Map<string, { point: Point; name: string }>();

    for (const e of edges) {
      if ((e.data as { _focused?: boolean } | undefined)?._focused !== true) continue;
      const storeId = wireStoreEndpoint(e);
      if (storeId == null) continue;
      const procId = storeId === e.source ? e.target : e.source;
      if (byStore.has(storeId)) continue;

      const storeInt = getInternalNode(storeId);
      const procInt = getInternalNode(procId);
      if (!storeInt || !procInt) continue;

      const storePt = screenCenter(
        storeInt.internals.positionAbsolute, storeInt.measured, 80, transform,
      );
      const procPt = screenCenter(
        procInt.internals.positionAbsolute, procInt.measured, 140, transform,
      );
      if (!storePt || !procPt) continue;
      // Store on screen → nothing to label (the wire is fully visible).
      if (isInsideRect(storePt, rect)) continue;

      const crossing = offscreenBoundaryPoint(procPt, storePt, rect);
      if (!crossing) continue;

      const name = String(
        (getNode(storeId)?.data as { label?: unknown } | undefined)?.label ?? storeId,
      );
      byStore.set(storeId, { point: crossing, name });
    }
    return [...byStore.entries()].map(([id, v]) => ({ id, ...v }));
  }, [edges, transform, width, height, getInternalNode, getNode]);

  if (labels.length === 0) return null;

  // Clamp each pill just inside the pane so it never renders half-off the edge.
  const M = 10;
  const clamp = (v: number, hi: number) => Math.max(M, Math.min(hi - M, v));

  return (
    <div className="loom-boundary-layer">
      {labels.map(({ id, point, name }) => (
        <div
          key={id}
          className="loom-boundary-label"
          title={`${name} (off-screen) — click to center`}
          style={{ left: clamp(point.x, width), top: clamp(point.y, height) }}
          onClick={() => {
            const n = getInternalNode(id);
            const p = n?.internals.positionAbsolute;
            if (!p) return;
            const w = n?.measured?.width ?? 80;
            const h = n?.measured?.height ?? 80;
            setCenter(p.x + w / 2, p.y + h / 2, { zoom: transform[2], duration: 300 });
          }}
        >
          <span className="loom-boundary-chevron">›</span>
          <span className="loom-boundary-name">{name}</span>
        </div>
      ))}
    </div>
  );
}

export default memo(BoundaryLabelsImpl);

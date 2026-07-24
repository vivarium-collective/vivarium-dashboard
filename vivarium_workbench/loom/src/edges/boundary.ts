// src/edges/boundary.ts — pure geometry for off-screen wire boundary labels.
//
// When a focused wire runs from an on-screen process to a store that has been
// panned/zoomed OFF the viewport, we label the store's NAME at the point where
// the wire crosses the viewport edge. That crossing point is a pure function of
// two screen-space points and the viewport rectangle — isolated here so it can
// be unit-tested without mounting React Flow (jsdom renders no real edges).

import type { Point } from './geometry';

/** Axis-aligned viewport rectangle with its top-left at the origin (0, 0). */
export interface Rect {
  width: number;
  height: number;
}

/** Whether `p` lies within (or on) the rectangle [0,width] × [0,height]. */
export function isInsideRect(p: Point, rect: Rect): boolean {
  return p.x >= 0 && p.x <= rect.width && p.y >= 0 && p.y <= rect.height;
}

/**
 * The point where the segment `anchor → store` leaves the viewport rectangle,
 * heading toward the (off-screen) `store` — i.e. where the wire is visually cut
 * off at the viewport edge. Screen coordinates, rectangle rooted at (0, 0).
 *
 *  - Returns `null` when `store` is INSIDE the rectangle (both endpoints on
 *    screen → nothing to label).
 *  - Returns `null` when the segment never crosses the rectangle at all (both
 *    endpoints off-screen on the same side, or the wire misses the viewport).
 *  - Otherwise returns the exit crossing, which lies exactly ON the rectangle
 *    boundary.
 *
 * Liang–Barsky segment clipping: parametrize P(t) = anchor + t·(store−anchor),
 * t ∈ [0,1]; clip to the rect; the exit toward `store` is the clipped `t1`.
 */
export function offscreenBoundaryPoint(
  anchor: Point, store: Point, rect: Rect,
): Point | null {
  // A degenerate viewport has no interior to cross into — nothing to label.
  // Guarded at the overlay call site too, but keep the pure helper total.
  if (rect.width <= 0 || rect.height <= 0) return null;
  if (isInsideRect(store, rect)) return null;

  const dx = store.x - anchor.x;
  const dy = store.y - anchor.y;
  const p = [-dx, dx, -dy, dy];
  const q = [anchor.x - 0, rect.width - anchor.x, anchor.y - 0, rect.height - anchor.y];

  let t0 = 0;
  let t1 = 1;
  for (let i = 0; i < 4; i++) {
    if (p[i] === 0) {
      // Segment is parallel to this edge; reject if it starts outside it.
      if (q[i] < 0) return null;
    } else {
      const r = q[i] / p[i];
      if (p[i] < 0) {
        if (r > t1) return null;
        if (r > t0) t0 = r;
      } else {
        if (r < t0) return null;
        if (r < t1) t1 = r;
      }
    }
  }
  if (t1 < t0) return null;

  // `t1` is the parameter at which the (clipped) segment exits the rectangle
  // toward the off-screen `store`; the point there is on the viewport boundary.
  return { x: anchor.x + t1 * dx, y: anchor.y + t1 * dy };
}

import { describe, it, expect } from 'vitest';
import { offscreenBoundaryPoint, isInsideRect, type Rect } from '../edges/boundary';

const RECT: Rect = { width: 200, height: 100 };

/** A point is ON the rectangle boundary if it touches one of the four edges
 *  (within a tiny epsilon) while staying within the rect's span. */
function onBoundary(p: { x: number; y: number }, rect: Rect): boolean {
  const eps = 1e-6;
  const onVert = (Math.abs(p.x) < eps || Math.abs(p.x - rect.width) < eps)
    && p.y >= -eps && p.y <= rect.height + eps;
  const onHoriz = (Math.abs(p.y) < eps || Math.abs(p.y - rect.height) < eps)
    && p.x >= -eps && p.x <= rect.width + eps;
  return onVert || onHoriz;
}

describe('isInsideRect', () => {
  it('is true inside and on the boundary, false outside', () => {
    expect(isInsideRect({ x: 100, y: 50 }, RECT)).toBe(true);
    expect(isInsideRect({ x: 0, y: 0 }, RECT)).toBe(true);
    expect(isInsideRect({ x: 200, y: 100 }, RECT)).toBe(true);
    expect(isInsideRect({ x: 201, y: 50 }, RECT)).toBe(false);
    expect(isInsideRect({ x: 100, y: -1 }, RECT)).toBe(false);
  });
});

describe('offscreenBoundaryPoint', () => {
  it('returns null when the store endpoint is on-screen (both inside)', () => {
    expect(offscreenBoundaryPoint({ x: 20, y: 20 }, { x: 150, y: 80 }, RECT)).toBeNull();
  });

  it('returns a point ON the boundary for a store off the RIGHT edge', () => {
    const pt = offscreenBoundaryPoint({ x: 50, y: 50 }, { x: 500, y: 50 }, RECT);
    expect(pt).not.toBeNull();
    expect(pt!.x).toBeCloseTo(200);   // right edge
    expect(pt!.y).toBeCloseTo(50);
    expect(onBoundary(pt!, RECT)).toBe(true);
  });

  it('returns the crossing for a store off the TOP edge', () => {
    const pt = offscreenBoundaryPoint({ x: 50, y: 50 }, { x: 50, y: -100 }, RECT);
    expect(pt).not.toBeNull();
    expect(pt!.y).toBeCloseTo(0);     // top edge
    expect(pt!.x).toBeCloseTo(50);
    expect(onBoundary(pt!, RECT)).toBe(true);
  });

  it('returns the crossing for a store off the BOTTOM-LEFT (diagonal)', () => {
    // From center heading down-left; the exit is on whichever edge it hits first.
    const pt = offscreenBoundaryPoint({ x: 100, y: 50 }, { x: -100, y: 150 }, RECT);
    expect(pt).not.toBeNull();
    expect(onBoundary(pt!, RECT)).toBe(true);
  });

  it('returns null when the segment never crosses the viewport', () => {
    // Both endpoints off-screen to the left, wire runs parallel outside — no
    // intersection with the rectangle at all.
    expect(offscreenBoundaryPoint({ x: -50, y: 50 }, { x: -10, y: 50 }, RECT)).toBeNull();
  });

  it('still crosses when BOTH endpoints are off-screen but the wire spans the rect', () => {
    const pt = offscreenBoundaryPoint({ x: -50, y: 50 }, { x: 400, y: 50 }, RECT);
    expect(pt).not.toBeNull();
    // Exit toward the off-screen store is the RIGHT edge.
    expect(pt!.x).toBeCloseTo(200);
    expect(onBoundary(pt!, RECT)).toBe(true);
  });

  it('treats a store exactly ON the boundary as on-screen (no label)', () => {
    // The store endpoint sits on the right edge — inside-or-on the rect, so
    // there is no off-screen crossing to label.
    expect(offscreenBoundaryPoint({ x: 100, y: 50 }, { x: 200, y: 50 }, RECT)).toBeNull();
  });

  it('does not throw and yields no crossing for a degenerate zero-size viewport', () => {
    // Guarded at the overlay call site, but the pure helper must stay total:
    // a 0×0 rect has no interior, so any distinct off-screen store yields null
    // rather than NaN or a throw.
    const zero: Rect = { width: 0, height: 0 };
    expect(() => offscreenBoundaryPoint({ x: 0, y: 0 }, { x: 50, y: 50 }, zero)).not.toThrow();
    expect(offscreenBoundaryPoint({ x: 0, y: 0 }, { x: 50, y: 50 }, zero)).toBeNull();
  });
});

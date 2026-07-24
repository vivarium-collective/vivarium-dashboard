import { describe, it, expect } from 'vitest';
import type { Node, Edge } from '@xyflow/react';

import { stateToReactFlow, defaultCollapsedIds } from '../convert';
import { retargetEdgesToVisible } from '../panels/filterHidden';
import { hierarchyMode } from '../layouts/hierarchy';
import type { LayoutContext, ZoomTierId } from '../layouts/types';
import fixture from './fixtures/v2ecoli-baseline.json';

const ctx = (tier: ZoomTierId): LayoutContext => ({
  compositeId: 'v2ecoli-baseline', tier, granularity: 0.5,
});

/** Reproduce App's visible-node computation: drop descendants of the
 *  default-collapsed groups, then re-target edges onto the visible set. */
function visibleGraph(): { nodes: Node[]; edges: Edge[] } {
  const raw = stateToReactFlow(fixture);
  const nodes = raw.nodes as unknown as Node[];
  const edges = raw.edges as unknown as Edge[];
  const collapsed = defaultCollapsedIds(fixture);
  const isHidden = (n: Node) => {
    const path: string[] = (n.data as { path?: string[] })?.path ?? [];
    for (let i = 1; i < path.length; i++) {
      if (collapsed.has(path.slice(0, i).join('.'))) return true;
    }
    return false;
  };
  const visibleNodes = nodes
    .filter((n) => !isHidden(n))
    .map((n) => (collapsed.has(n.id)
      ? { ...n, data: { ...n.data, isCollapsed: true } } : n));
  const visibleIds = new Set(visibleNodes.map((n) => n.id));
  const visibleEdges = retargetEdgesToVisible(edges, visibleIds);
  return { nodes: visibleNodes, edges: visibleEdges };
}

describe('hierarchy hub-wire reduction (baseline fixture)', () => {
  it('hides most wires by default, keeping place + non-hub wires', () => {
    // Measured on the raw stateToReactFlow output (brief's before/after harness).
    const edges = stateToReactFlow(fixture).edges as unknown as Edge[];
    const before = (edges as Edge[]).length;
    const after = hierarchyMode.edgeVisibility!(
      edges as Edge[],
      { focused: new Set(), pinned: new Set() },
      [],
    ).length;
    // eslint-disable-next-line no-console
    console.log(`[hier-redesign] drawn edges — before=${before} after=${after}`);
    expect(after).toBeLessThan(before);
    // The reduction is substantial (hub wires are most of the graph).
    expect(after).toBeLessThan(before * 0.6);
    // Place edges (the store hierarchy) always survive.
    const placeCount = (edges as Edge[])
      .filter((e) => (e.data as { edgeType?: string })?.edgeType === 'place').length;
    expect(after).toBeGreaterThanOrEqual(placeCount);
  });

  it('toggle ON draws every edge (identity)', () => {
    const edges = stateToReactFlow(fixture).edges as unknown as Edge[];
    const out = hierarchyMode.edgeVisibility!(
      edges as Edge[],
      { focused: new Set(), pinned: new Set(), showHubWires: true },
      [],
    );
    expect(out).toBe(edges);
  });
});

describe('hierarchy layout — no node overlaps at the full tier', () => {
  it('places every node without a single pairwise bounding-box overlap', async () => {
    const { nodes, edges } = visibleGraph();
    const { nodes: laid } = await hierarchyMode.run(nodes, edges, ctx('full'));

    // Each node carries the ELK footprint it was sized with (data._elkW/_elkH),
    // stamped by hierarchyMode.run — the exact rectangle ELK reserved. Overlap
    // is checked against those rectangles.
    type Box = { id: string; x: number; y: number; w: number; h: number };
    const boxes: Box[] = laid.map((n) => {
      const d = n.data as { _elkW?: number; _elkH?: number };
      return {
        id: n.id,
        x: n.position.x,
        y: n.position.y,
        w: typeof d._elkW === 'number' ? d._elkW : (n.type === 'process' ? 140 : 80),
        h: typeof d._elkH === 'number' ? d._elkH : (n.type === 'process' ? 60 : 80),
      };
    });

    // Every node got a finite position.
    for (const b of boxes) {
      expect(Number.isFinite(b.x)).toBe(true);
      expect(Number.isFinite(b.y)).toBe(true);
    }

    // Pairwise AABB overlap — strict (touching edges are allowed). A tiny
    // epsilon absorbs floating-point rounding at shared borders.
    const EPS = 0.5;
    const overlaps: string[] = [];
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        const overlapX = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
        const overlapY = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
        if (overlapX > EPS && overlapY > EPS) {
          overlaps.push(`${a.id} ∩ ${b.id} (${overlapX.toFixed(0)}×${overlapY.toFixed(0)})`);
        }
      }
    }
    // eslint-disable-next-line no-console
    console.log(`[hier-redesign] full-tier nodes=${boxes.length} overlaps=${overlaps.length}`);
    expect(overlaps).toEqual([]);
  });
});

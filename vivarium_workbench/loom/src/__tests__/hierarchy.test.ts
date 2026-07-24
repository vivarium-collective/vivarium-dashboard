import { describe, it, expect } from 'vitest';

import { hierarchyMode } from '../layouts/hierarchy';
import { TIERS } from '../layouts/tiers';
import type { LayoutContext, ZoomTierId } from '../layouts/types';

const ctx = (tier: ZoomTierId): LayoutContext => ({
  compositeId: null, tier, granularity: 0.5,
});

// A store plus two processes: the two processes land in the same grid column
// (maxRows >= 6 for n=2), so their vertical pitch is exactly PROC_H + gap — and
// PROC_H is the tier's cardHeight. A higher tier therefore spreads them farther.
const NODES = [
  { id: 's',  type: 'store',   data: { path: ['s'] },  position: { x: 0, y: 0 } },
  { id: 'p1', type: 'process', data: { path: ['p1'] }, position: { x: 0, y: 0 } },
  { id: 'p2', type: 'process', data: { path: ['p2'] }, position: { x: 0, y: 0 } },
];

const rowPitch = (out: { nodes: Array<{ id: string; position: { y: number } }> }) => {
  const a = out.nodes.find((n) => n.id === 'p1')!.position.y;
  const b = out.nodes.find((n) => n.id === 'p2')!.position.y;
  return Math.abs(b - a);
};

describe('hierarchyMode semantic zoom', () => {
  it('exposes the shared tier ladder', () => {
    expect(hierarchyMode.tiers).toBe(TIERS);
  });

  it('sizes ELK/grid nodes by the ctx tier (higher tier → more spacing)', async () => {
    const glyph = await hierarchyMode.run(NODES as any, [], ctx('glyph'));
    const full = await hierarchyMode.run(NODES as any, [], ctx('full'));
    // Card height grows glyph(56) → full(320), so the process rows spread apart.
    expect(rowPitch(full)).toBeGreaterThan(rowPitch(glyph));
  });

  it('does not mutate the caller-supplied nodes (stamps hints on copies)', async () => {
    await hierarchyMode.run(NODES as any, [], ctx('full'));
    for (const n of NODES) {
      expect((n.data as Record<string, unknown>)._elkW).toBeUndefined();
      expect((n.data as Record<string, unknown>)._elkH).toBeUndefined();
    }
  });
});

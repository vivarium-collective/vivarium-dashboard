import { describe, it, expect } from 'vitest';
import { composeSeriesSvg, type SeriesPanel } from '../snapshotSeries';

const frameSvg = (w: number, h: number, tag: string) =>
  `<?xml version="1.0" encoding="UTF-8"?>\n<svg width="${w}" height="${h}"><rect id="${tag}"/></svg>`;

describe('composeSeriesSvg', () => {
  const panels: SeriesPanel[] = [
    { svg: frameSvg(400, 500, 'a'), png: null, label: 'One cell', sub: 'frame 0' },
    { svg: frameSvg(800, 500, 'b'), png: null, label: 'Divides', sub: 'frame 6' },
  ];

  it('embeds one <image> per panel and one arrow between them', () => {
    const out = composeSeriesSvg(panels);
    expect((out.match(/<image /g) || []).length).toBe(2);
    expect((out.match(/<polygon /g) || []).length).toBe(1); // arrow head between the two
  });

  it('labels each panel with its name and sub-line', () => {
    const out = composeSeriesSvg(panels);
    expect(out).toContain('One cell');
    expect(out).toContain('Divides');
    expect(out).toContain('frame 0');
    expect(out).toContain('frame 6');
  });

  it('scales every panel to a common height and sizes the canvas to fit', () => {
    const out = composeSeriesSvg(panels);
    // both panels normalized to the same image height
    const heights = [...out.matchAll(/<image [^>]*height="([\d.]+)"/g)].map((m) => parseFloat(m[1]));
    expect(heights.length).toBe(2);
    expect(heights[0]).toBeCloseTo(heights[1], 3);
    // outer svg width is positive and encloses both scaled panels
    const w = parseFloat((out.match(/<svg[^>]*width="(\d+)"/) || [])[1] || '0');
    expect(w).toBeGreaterThan(0);
  });

  it('skips panels with no svg', () => {
    const out = composeSeriesSvg([panels[0], { svg: null, png: null, label: 'empty' }]);
    expect((out.match(/<image /g) || []).length).toBe(1);
  });

  it('escapes markup in labels', () => {
    const out = composeSeriesSvg([{ svg: frameSvg(400, 500, 'a'), png: null, label: 'a<b>&c' }]);
    expect(out).toContain('a&lt;b&gt;&amp;c');
    expect(out).not.toContain('<b>&c');
  });
});

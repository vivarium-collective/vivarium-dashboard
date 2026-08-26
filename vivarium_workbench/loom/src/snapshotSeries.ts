// src/snapshotSeries.ts — compose a set of saved snapshots into ONE side-by-side
// series figure (the place-graph topology at each saved frame, left to right)
// and hand it to the browser as PNG, SVG, and/or a zip of the individual frames.
//
// The per-frame SVG/PNG come from the loom's own headless export hooks
// (window.__loomExportSvg / __loomExportPng) applied to each saved state in turn
// — so a series is exactly what you'd get by Viewing each save-point and
// exporting it, stitched into one image with stage labels and arrows.
import { zipSync, strToU8 } from 'fflate';

export interface SeriesPanel {
  /** Per-frame SVG string (from __loomExportSvg). */
  svg: string | null;
  /** Per-frame PNG data URL (from __loomExportPng). */
  png: string | null;
  /** Bold stage label above the panel. */
  label: string;
  /** Subtle line under the label (e.g. "f3/5"). */
  sub?: string;
}

export type SeriesFormat = 'png' | 'svg' | 'zip';

const PANEL_H = 640;      // common panel height (px) the frames are scaled to
const GAP = 90;           // horizontal gap between panels (holds the arrow)
const PAD = 48;           // outer padding
const TITLE_H = 74;       // header band height above each panel
const CAPTION_H = 0;      // (reserved)
const INK = '#182028';
const SUBTLE = '#6e7883';
const ARROW = '#5a646e';
const BG = '#ffffff';

function _svgSize(svg: string): { w: number; h: number } {
  const wm = svg.match(/\bwidth="([\d.]+)"/);
  const hm = svg.match(/\bheight="([\d.]+)"/);
  if (wm && hm) return { w: parseFloat(wm[1]), h: parseFloat(hm[1]) };
  const vb = svg.match(/viewBox="[\d.]+ [\d.]+ ([\d.]+) ([\d.]+)"/);
  if (vb) return { w: parseFloat(vb[1]), h: parseFloat(vb[2]) };
  return { w: 400, h: 400 };
}

function _b64(s: string): string {
  // UTF-8 safe base64 for embedding an SVG as a data URI.
  return btoa(unescape(encodeURIComponent(s)));
}

function _loadImg(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

/** Compose the panels' SVGs into one vector series SVG (each frame embedded as an
 *  <image>, so every panel keeps its own coordinate system). */
export function composeSeriesSvg(panels: SeriesPanel[]): string {
  const usable = panels.filter((p) => p.svg);
  const sized = usable.map((p) => {
    const { w, h } = _svgSize(p.svg as string);
    const scale = PANEL_H / h;
    return { p, w: w * scale, h: PANEL_H };
  });
  const colW = Math.max(1, ...sized.map((s) => s.w));
  const n = sized.length;
  const totalW = PAD * 2 + colW * n + GAP * (n - 1);
  const totalH = PAD * 2 + TITLE_H + PANEL_H + CAPTION_H;
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const parts: string[] = [];
  parts.push(`<?xml version="1.0" encoding="UTF-8"?>`);
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${Math.ceil(totalW)}" height="${Math.ceil(totalH)}" viewBox="0 0 ${Math.ceil(totalW)} ${Math.ceil(totalH)}" font-family="system-ui, Arial, sans-serif">`);
  parts.push(`<rect width="100%" height="100%" fill="${BG}"/>`);
  sized.forEach((s, i) => {
    const x0 = PAD + i * (colW + GAP);
    const cx = x0 + colW / 2;
    const px = x0 + (colW - s.w) / 2;
    const href = 'data:image/svg+xml;base64,' + _b64(s.p.svg as string);
    parts.push(`<text x="${cx}" y="${PAD + 30}" text-anchor="middle" font-size="26" font-weight="700" fill="${INK}">${esc(s.p.label)}</text>`);
    if (s.p.sub) parts.push(`<text x="${cx}" y="${PAD + 58}" text-anchor="middle" font-size="20" fill="${SUBTLE}">${esc(s.p.sub)}</text>`);
    parts.push(`<image x="${px}" y="${PAD + TITLE_H}" width="${s.w}" height="${s.h}" xlink:href="${href}"/>`);
    if (i < n - 1) {
      const ay = PAD + TITLE_H + PANEL_H / 2;
      const gx0 = x0 + colW + 18, gx1 = x0 + colW + GAP - 18;
      parts.push(`<line x1="${gx0}" y1="${ay}" x2="${gx1 - 10}" y2="${ay}" stroke="${ARROW}" stroke-width="5"/>`);
      parts.push(`<polygon points="${gx1 - 10},${ay - 12} ${gx1 - 10},${ay + 12} ${gx1 + 6},${ay}" fill="${ARROW}"/>`);
    }
  });
  parts.push(`</svg>`);
  return parts.join('\n');
}

/** Compose the panels' PNGs onto one canvas, side by side with labels + arrows. */
export async function composeSeriesPng(panels: SeriesPanel[]): Promise<Blob> {
  const usable = panels.filter((p) => p.png);
  const imgs = await Promise.all(usable.map((p) => _loadImg(p.png as string)));
  const scaled = imgs.map((img) => ({ w: img.width * (PANEL_H / img.height), h: PANEL_H, img }));
  const colW = Math.max(1, ...scaled.map((s) => s.w));
  const n = scaled.length;
  const totalW = PAD * 2 + colW * n + GAP * (n - 1);
  const totalH = PAD * 2 + TITLE_H + PANEL_H;

  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(totalW);
  canvas.height = Math.ceil(totalH);
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('no 2d context');
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.textAlign = 'center';

  scaled.forEach((s, i) => {
    const x0 = PAD + i * (colW + GAP);
    const cx = x0 + colW / 2;
    ctx.fillStyle = INK;
    ctx.font = '700 26px system-ui, Arial, sans-serif';
    ctx.fillText(usable[i].label, cx, PAD + 30);
    if (usable[i].sub) {
      ctx.fillStyle = SUBTLE;
      ctx.font = '20px system-ui, Arial, sans-serif';
      ctx.fillText(usable[i].sub as string, cx, PAD + 56);
    }
    ctx.drawImage(s.img, x0 + (colW - s.w) / 2, PAD + TITLE_H, s.w, s.h);
    if (i < n - 1) {
      const ay = PAD + TITLE_H + PANEL_H / 2;
      const gx0 = x0 + colW + 18, gx1 = x0 + colW + GAP - 18;
      ctx.strokeStyle = ARROW; ctx.fillStyle = ARROW; ctx.lineWidth = 5;
      ctx.beginPath(); ctx.moveTo(gx0, ay); ctx.lineTo(gx1 - 10, ay); ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(gx1 - 10, ay - 12); ctx.lineTo(gx1 - 10, ay + 12); ctx.lineTo(gx1 + 6, ay);
      ctx.closePath(); ctx.fill();
    }
  });
  return await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob failed'))), 'image/png'));
}

function _download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function _dataUrlToU8(dataUrl: string): Uint8Array {
  const b64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}

/** Build and download the requested formats for a set of snapshot panels. */
export async function exportSeries(
  panels: SeriesPanel[], formats: Set<SeriesFormat>, baseName: string,
): Promise<void> {
  const base = (baseName || 'composite').replace(/[^a-zA-Z0-9._-]/g, '_');
  const seriesSvg = (formats.has('svg') || formats.has('zip')) ? composeSeriesSvg(panels) : null;
  const seriesPngBlob = (formats.has('png') || formats.has('zip')) ? await composeSeriesPng(panels) : null;

  if (formats.has('png') && seriesPngBlob) _download(seriesPngBlob, `${base}-series.png`);
  if (formats.has('svg') && seriesSvg) _download(new Blob([seriesSvg], { type: 'image/svg+xml' }), `${base}-series.svg`);

  if (formats.has('zip')) {
    const files: Record<string, Uint8Array> = {};
    panels.forEach((p, i) => {
      const stem = `frame_${i}_${(p.label || '').replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 40) || i}`;
      if (p.svg) files[`${stem}.svg`] = strToU8(p.svg);
      if (p.png) files[`${stem}.png`] = _dataUrlToU8(p.png);
    });
    if (seriesSvg) files['series.svg'] = strToU8(seriesSvg);
    if (seriesPngBlob) files['series.png'] = new Uint8Array(await seriesPngBlob.arrayBuffer());
    const zipped = zipSync(files, { level: 6 });
    _download(new Blob([zipped as BlobPart], { type: 'application/zip' }), `${base}-snapshots.zip`);
  }
}

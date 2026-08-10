// src/nodes/InnerCompositePreview.tsx — a live thumbnail of a Composite
// Process's INNER composite, rendered inside its card (in place of the
// contract) at high zoom. Lazily fetches /api/composite-inner-state (the same
// endpoint the drill-down uses), converts it to nodes/edges, lays them out with
// the sync depth-stack layout, and draws a scaled-to-fit static SVG mini-map.
//
// The inner build is ParCa-heavy (a few seconds the first time), so the fetch
// is lazy + module-cached + shows a "building…" placeholder. Double-clicking
// the card still opens the full drill-down view (App's onNodeDoubleClick).

import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import {
  stateToReactFlow, defaultCollapsedIds, defaultHiddenIds,
} from '../convert';
import { fetchInnerComposite } from '../api';

type Graph = { nodes: any[]; edges: any[] };
type CacheEntry = { status: 'loading' | 'ready' | 'error'; graph?: Graph; error?: string };

// Module-level cache keyed by the drill target, so re-renders / re-mounts (and
// both colony cells sharing the same inner model shape) never refetch.
const _CACHE = new Map<string, CacheEntry>();
const _WAITERS = new Map<string, Set<() => void>>();

function _key(rootId: string, hops: string[][]): string {
  return rootId + '::' + JSON.stringify(hops);
}

function _notify(key: string) {
  (_WAITERS.get(key) ?? new Set()).forEach((cb) => cb());
}

/** Fetch the inner state, retrying transient failures with backoff. The inner
 *  build runs in an env-worker warm pool that can be briefly unavailable (503)
 *  right after a server (re)start, and the first cold build is a few seconds —
 *  a single attempt turns those into a permanent "preview unavailable". Retry a
 *  few times before giving up so the preview renders on its own. */
async function _fetchWithRetry(rootId: string, hops: string[][], tries = 4) {
  let lastErr: any;
  for (let i = 0; i < tries; i++) {
    try {
      return await fetchInnerComposite(rootId, hops);
    } catch (e) {
      lastErr = e;
      if (i < tries - 1) await new Promise((r) => setTimeout(r, 700 * (i + 1)));
    }
  }
  throw lastErr;
}

async function _load(rootId: string, hops: string[][]) {
  const key = _key(rootId, hops);
  const cur = _CACHE.get(key);
  // Load once; but a prior ERROR is retryable (click-to-retry re-enters here).
  if (cur && cur.status !== 'error') return;
  _CACHE.set(key, { status: 'loading' });
  _notify(key);
  try {
    const res = await _fetchWithRetry(rootId, hops);
    _CACHE.set(key, { status: 'ready', graph: _overviewGraph(res.state) });
  } catch (e: any) {
    _CACHE.set(key, { status: 'error', error: e?.message || String(e) });
  }
  _notify(key);
}

/** The OVERVIEW subset of a composite for the thumbnail: the full state has
 *  hundreds of deep leaf stores (a WCM has ~476), which scale to sub-pixel dots
 *  and swamp the processes. Collapse deep container stores + hide bookkeeping
 *  noise (the same defaults the full canvas opens with), so the thumbnail shows
 *  the processes + top-level stores — a legible map, not a grey haze. */
function _overviewGraph(state: any): Graph {
  const all = stateToReactFlow(state);
  const collapsed = defaultCollapsedIds(state);
  const hidden = defaultHiddenIds(state);
  const underCollapsed = (path: string[]) => {
    for (let i = 1; i < path.length; i++) {
      if (collapsed.has(path.slice(0, i).join('.'))) return true;
    }
    return false;
  };
  const nodes = all.nodes.filter(
    (n) => !hidden.has(n.id) && !underCollapsed((n.data as any)?.path ?? []),
  );
  const ids = new Set(nodes.map((n) => n.id));
  const edges = all.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  return { nodes, edges };
}

/** Warm the cache for a Composite Process's inner composite in the background,
 *  so its in-card mini-map renders instantly when the user zooms in (no
 *  "building…" flash). No-op if already loaded/loading. */
export function prefetchInner(rootId: string, hops: string[][]) {
  if (!_CACHE.has(_key(rootId, hops))) _load(rootId, hops);
}

const PROC = { w: 150, h: 52 };
const STORE = { w: 60, h: 60 };

/** Truncate a process label to fit inside the mini-card. */
function _short(label: string, max = 13): string {
  if (!label) return '';
  return label.length > max ? label.slice(0, max - 1) + '…' : label;
}

/** Compact grid layout for the thumbnail — tight gaps so the nodes FILL the box
 *  (the shared depth-stack layout uses full-card-size gaps, which shrink these
 *  mini nodes to nothing). Stores in a band on top, processes in a grid below;
 *  columns chosen so the whole figure roughly matches the card's aspect and fits
 *  with no scrolling. Returns top-left positions by node id. */
function _miniLayout(nodes: any[]): Map<string, { x: number; y: number }> {
  const procs = nodes.filter((n) => n.type === 'process');
  const stores = nodes.filter((n) => n.type !== 'process');
  const pos = new Map<string, { x: number; y: number }>();

  const SG_X = 26, SG_Y = 46;   // store grid gaps (room above dot for its label)
  const PG_X = 40, PG_Y = 48;   // process grid gaps
  const colsS = Math.max(1, Math.round(Math.sqrt(stores.length * 3.2)));
  // Soft depth alignment: group stores by bigraph depth (path length) and stack
  // the groups in bands top→bottom, so stores keep SOME preference for aligning
  // by depth while still wrapping (not a strict single row per depth).
  const depthOf = (n: any) =>
    Math.max(1, ((n.data?.path as unknown[] | undefined)?.length ?? 1));
  const byDepth = new Map<number, any[]>();
  for (const s of stores) {
    const d = depthOf(s);
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(s);
  }
  let sy = 0;
  for (const d of [...byDepth.keys()].sort((a, b) => a - b)) {
    const grp = byDepth.get(d)!
      .slice()
      .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    grp.forEach((s, i) => {
      pos.set(s.id, {
        x: (i % colsS) * (STORE.w + SG_X),
        y: sy + Math.floor(i / colsS) * (STORE.h + SG_Y),
      });
    });
    const rows = Math.max(1, Math.ceil(grp.length / colsS));
    sy += rows * (STORE.h + SG_Y) + 14;  // small gap between depth bands
  }
  const bandH = sy + 20;

  const colsP = Math.max(1, Math.round(Math.sqrt(procs.length * 1.9)));
  procs.forEach((n, i) => {
    pos.set(n.id, {
      x: (i % colsP) * (PROC.w + PG_X),
      y: bandH + Math.floor(i / colsP) * (PROC.h + PG_Y),
    });
  });
  return pos;
}

/** Draw the laid-out inner graph as a scaled static SVG mini-map: real
 *  labelled process cards, small store dots, thin wires. Aspect-fit (the SVG box
 *  matches the content's aspect via width:100%/height:auto), so the graph fills
 *  the width with no wasted vertical margins. */
function MiniMap(props: { graph: Graph }) {
  const { nodes, edges } = props.graph;
  const posById = _miniLayout(nodes);
  const sizeOf = (n: any) => (n.type === 'process' ? PROC : STORE);
  const centerById = new Map<string, { x: number; y: number }>();

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of nodes) {
    const p = posById.get(n.id);
    if (!p) continue;
    const s = sizeOf(n);
    minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + s.w); maxY = Math.max(maxY, p.y + s.h);
    centerById.set(n.id, { x: p.x + s.w / 2, y: p.y + s.h / 2 });
  }
  if (!isFinite(minX)) return null;
  const pad = 16;
  const w = maxX - minX + pad * 2, h = maxY - minY + pad * 2;
  const vb = `${minX - pad} ${minY - pad} ${w} ${h}`;
  const Cx = minX - pad + w / 2, Cy = minY - pad + h / 2;
  const sw = Math.max(1, Math.max(w, h) / 700);
  const lbl = PROC.h * 0.42;

  const procCount = nodes.filter((n) => n.type === 'process').length;
  const storeCount = nodes.length - procCount;
  const drawEdges = edges.length <= 800;

  // --- Interaction: wheel-zoom (center-anchored), drag-pan, click-select.
  // Contained: wheel/mousedown stopPropagation so the OUTER canvas doesn't also
  // zoom/drag. Double-click still bubbles to the card → opens the full view.
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [k, setK] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [sel, setSel] = useState<string | null>(null);
  const drag = useRef<{ sx: number; sy: number; px: number; py: number } | null>(null);
  const tx = Cx * (1 - k) + pan.x, ty = Cy * (1 - k) + pan.y;

  const onWheel = (e: React.WheelEvent) => {
    e.stopPropagation();
    const f = e.deltaY < 0 ? 1.18 : 1 / 1.18;
    setK((cur) => Math.min(10, Math.max(1, cur * f)));
  };
  const onDown = (e: React.MouseEvent) => {
    e.stopPropagation();
    drag.current = { sx: e.clientX, sy: e.clientY, px: pan.x, py: pan.y };
  };
  const onMove = (e: React.MouseEvent) => {
    const d = drag.current, el = svgRef.current;
    if (!d || !el) return;
    const rect = el.getBoundingClientRect();
    setPan({
      x: d.px + ((e.clientX - d.sx) / rect.width) * w,
      y: d.py + ((e.clientY - d.sy) / rect.height) * h,
    });
  };
  const onUp = () => { drag.current = null; };
  const reset = (e: React.MouseEvent) => { e.stopPropagation(); setK(1); setPan({ x: 0, y: 0 }); };
  const panned = k !== 1 || pan.x !== 0 || pan.y !== 0;

  return (
    <div className="inner-preview">
      <div className="inner-preview-head">
        <span className="inner-preview-badge">⤢ inner composite</span>
        <span className="inner-preview-count">
          {procCount} processes · {storeCount} stores · drag / scroll
          {panned && <button className="mini-reset" onClick={reset} title="Reset view">reset</button>}
        </span>
      </div>
      <svg
        ref={svgRef}
        /* nodrag/nowheel: let THIS element handle drag + wheel instead of the
           outer React Flow canvas (which owns node-drag + pane-zoom). */
        className="inner-preview-svg nodrag nowheel"
        viewBox={vb}
        preserveAspectRatio="xMidYMid meet"
        style={{ aspectRatio: `${w} / ${h}`, cursor: 'grab' }}
        onWheel={onWheel}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        onMouseLeave={onUp}
      >
        <g transform={`translate(${tx} ${ty}) scale(${k})`}>
        {drawEdges && edges.map((e: any) => {
          const a = centerById.get(e.source);
          const b = centerById.get(e.target);
          if (!a || !b) return null;
          const hot = sel != null && (e.source === sel || e.target === sel);
          const place = e.data?.edgeType === 'place';
          return (
            <line
              key={e.id}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={hot ? '#2563eb' : place ? '#cbd5e1' : '#bcd4f5'}
              strokeWidth={hot ? sw * 2 : place ? sw * 1.2 : sw}
              strokeOpacity={hot ? 0.9 : place ? 0.5 : 0.4}
            />
          );
        })}
        {/* Stores as small labelled dots (behind). Hover shows the full name. */}
        {nodes.filter((n) => n.type !== 'process').map((n: any) => {
          const c = centerById.get(n.id);
          if (!c) return null;
          const name = n.data?.label ?? '';
          const on = sel === n.id;
          return (
            <g key={n.id} className={`mini-store${on ? ' is-sel' : ''}`}
               onClick={(e) => { e.stopPropagation(); setSel(on ? null : n.id); }}>
              <title>{name} (store)</title>
              <circle cx={c.x} cy={c.y} r={STORE.w / 1.7}
                fill={on ? '#dbeafe' : '#eef2f7'} stroke={on ? '#3b82f6' : '#b6c2d1'} strokeWidth={sw} />
              <text
                x={c.x} y={c.y - STORE.w / 1.3} fontSize={lbl * 0.82}
                textAnchor="middle" dominantBaseline="ideographic" fill="#64748b"
                fontFamily="ui-sans-serif, system-ui, sans-serif"
                className="mini-store-label"
              >
                {_short(name, 14)}
              </text>
            </g>
          );
        })}
        {/* Processes as clean labelled cards (on top). Hover shows full name. */}
        {nodes.filter((n) => n.type === 'process').map((n: any) => {
          const p = posById.get(n.id);
          if (!p) return null;
          const c = centerById.get(n.id)!;
          const name = n.data?.label ?? '';
          const on = sel === n.id;
          return (
            <g key={n.id} className={`mini-proc${on ? ' is-sel' : ''}`}
               onClick={(e) => { e.stopPropagation(); setSel(on ? null : n.id); }}>
              <title>{name} (process)</title>
              <rect
                x={p.x} y={p.y} width={PROC.w} height={PROC.h}
                fill={on ? '#eff6ff' : '#ffffff'} stroke={on ? '#1d4ed8' : '#3b82f6'}
                strokeWidth={on ? sw * 3.4 : sw * 2.2}
              />
              <text
                x={c.x} y={c.y} fontSize={lbl} textAnchor="middle"
                dominantBaseline="central" fill="#1e3a8a"
                fontFamily="ui-sans-serif, system-ui, sans-serif"
              >
                {_short(name, 16)}
              </text>
            </g>
          );
        })}
        </g>
      </svg>
    </div>
  );
}

export default function InnerCompositePreview(props: {
  rootId: string;
  hops: string[][];
  /** Auto-fetch on mount. When false, show a compact "render" button (the viz
   *  icon) instead — used at the `contract` tier to avoid a ParCa build on every
   *  card the moment zoom crosses the threshold; `full` tier auto-loads. */
  auto: boolean;
}) {
  const key = _key(props.rootId, props.hops);
  const [, bump] = useState(0);
  const entry = _CACHE.get(key);

  // Subscribe to cache changes for this key so async loads re-render the card.
  useEffect(() => {
    const cb = () => bump((n) => n + 1);
    let set = _WAITERS.get(key);
    if (!set) { set = new Set(); _WAITERS.set(key, set); }
    set.add(cb);
    return () => { set!.delete(cb); };
  }, [key]);

  // Auto-load once when requested and not yet started.
  useEffect(() => {
    if (props.auto && !_CACHE.has(key)) _load(props.rootId, props.hops);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, props.auto]);

  if (!entry) {
    // Idle (contract tier, not auto): show the viz icon to render on demand.
    return (
      <div
        className="inner-preview inner-preview-idle"
        title="Render a preview of this Composite Process's inner model"
        onClick={(e) => { e.stopPropagation(); _load(props.rootId, props.hops); }}
      >
        <span className="inner-preview-badge">⤢ inner composite</span>
        <span className="inner-preview-hint">click to preview · double-click to open</span>
      </div>
    );
  }
  if (entry.status === 'loading') {
    return (
      <div className="inner-preview inner-preview-loading">
        <span className="inner-preview-badge">⤢ inner composite</span>
        <span className="inner-preview-hint">building inner model…</span>
      </div>
    );
  }
  if (entry.status === 'error' || !entry.graph) {
    return (
      <div
        className="inner-preview inner-preview-error"
        title="Retry building the inner-composite preview"
        onClick={(e) => { e.stopPropagation(); _load(props.rootId, props.hops); }}
      >
        <span className="inner-preview-badge">⤢ inner composite</span>
        <span className="inner-preview-hint">preview unavailable — click to retry</span>
      </div>
    );
  }
  return <MiniMap graph={entry.graph} />;
}

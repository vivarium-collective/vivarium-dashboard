// src/panels/SavePointsMenu.tsx — run-bar controls for SAVE-POINTS.
//
// "⛿ Save" captures the CURRENT frame's state (name it, store in the browser or
// the workspace). "History ▾" lists every save-point for this composite; each
// can be Viewed (load its state into the graph) or reran-from (fork a new run
// seeded with it), or deleted.
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  listAll, save, remove, type SavePoint, type SavePointOrigin,
} from '../savepoints';
import { exportSeries, type SeriesFormat, type SeriesPanel } from '../snapshotSeries';

const spKey = (p: SavePoint) => p.origin + ':' + p.id;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface SavePointsMenuProps {
  compositeId: string | null;
  /** Current frame's emitted state to capture, or null when nothing is loaded. */
  captureState: () => Record<string, unknown> | null;
  currentFrame: number | null;
  frameCount: number | null;
  onView: (state: Record<string, unknown>) => void;
  onRerun: (state: Record<string, unknown>) => void;
  disabled?: boolean;
}

function ago(sec: number): string {
  const d = Date.now() / 1000 - sec;
  if (d < 60) return 'just now';
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

export function SavePointsMenu(props: SavePointsMenuProps) {
  const { compositeId } = props;
  const [saveOpen, setSaveOpen] = useState(false);
  const [histOpen, setHistOpen] = useState(false);
  const [points, setPoints] = useState<SavePoint[]>([]);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  // Series export: which save-points to include + which formats, plus progress.
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [fmt, setFmt] = useState<Set<SeriesFormat>>(new Set(['png', 'svg', 'zip'] as SeriesFormat[]));
  const [exporting, setExporting] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!compositeId) { setPoints([]); return; }
    setPoints(await listAll(compositeId));
  }, [compositeId]);

  useEffect(() => { void refresh(); }, [refresh]);
  // Close popovers on outside click.
  useEffect(() => {
    if (!saveOpen && !histOpen) return;
    const h = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setSaveOpen(false); setHistOpen(false);
      }
    };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [saveOpen, histOpen]);

  const canCapture = !!compositeId && !!props.captureState();

  const openSave = () => {
    setErr(null);
    setName(props.currentFrame != null ? `frame ${props.currentFrame}` : 'snapshot');
    setHistOpen(false); setSaveOpen(true);
  };

  const doSave = async (where: SavePointOrigin) => {
    const state = props.captureState();
    if (!compositeId || !state) { setErr('Nothing to capture — run first.'); return; }
    setBusy(true); setErr(null);
    try {
      await save(compositeId, where, {
        name, frame: props.currentFrame, n_frames: props.frameCount, state,
      });
      setSaveOpen(false);
      await refresh();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally { setBusy(false); }
  };

  const doDelete = async (p: SavePoint) => {
    if (!compositeId) return;
    await remove(compositeId, p);
    setSel((s) => { const n = new Set(s); n.delete(spKey(p)); return n; });
    await refresh();
  };

  const toggleSel = (p: SavePoint) => setSel((s) => {
    const n = new Set(s); const k = spKey(p);
    if (n.has(k)) n.delete(k); else n.add(k);
    return n;
  });
  const toggleFmt = (f: SeriesFormat) => setFmt((s) => {
    const n = new Set(s); if (n.has(f)) n.delete(f); else n.add(f);
    return n;
  });

  // Export the selected save-points as ONE side-by-side series. We drive the
  // live graph: capture the current state to restore, then for each selected
  // save-point (in frame order) load its state, let the layout settle, and grab
  // the loom's headless SVG/PNG export — exactly what "View then export" gives,
  // stitched into one figure by snapshotSeries.
  const doExport = async () => {
    const w = window as unknown as {
      __loomExportSvg?: () => Promise<string | null>;
      __loomExportPng?: () => Promise<string | null>;
    };
    if (!compositeId || !w.__loomExportSvg) { setErr('Nothing to export — run and render first.'); return; }
    if (fmt.size === 0) { setErr('Pick at least one format.'); return; }
    const chosen = points.filter((p) => sel.has(spKey(p)))
      .sort((a, b) => (a.frame ?? 0) - (b.frame ?? 0));
    if (chosen.length === 0) { setErr('Select one or more save-points to export.'); return; }

    const original = props.captureState();
    setErr(null);
    const panels: SeriesPanel[] = [];
    try {
      for (let i = 0; i < chosen.length; i++) {
        const p = chosen[i];
        setExporting(`Rendering ${i + 1}/${chosen.length}…`);
        props.onView(p.state);            // load this snapshot's state into the graph
        await sleep(600);                 // let the layout re-flow and re-fit
        const svg = fmt.has('svg') || fmt.has('zip') ? await w.__loomExportSvg!() : null;
        const png = fmt.has('png') || fmt.has('zip') ? (w.__loomExportPng ? await w.__loomExportPng() : null) : null;
        panels.push({
          svg, png, label: p.name,
          sub: p.frame != null ? `frame ${p.frame}${p.n_frames ? '/' + p.n_frames : ''}` : undefined,
        });
      }
      setExporting('Composing…');
      const base = (compositeId.split('.').pop() || 'composite') + '-snapshots';
      await exportSeries(panels, fmt, base);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      if (original) props.onView(original);   // restore the frame the user was on
      setExporting(null);
    }
  };

  return (
    <div className="sp-menu" ref={wrapRef}>
      <button type="button" className="sp-btn" onClick={openSave}
        disabled={props.disabled || !canCapture}
        title={canCapture ? 'Save the current frame as a save-point' : 'Run first, then save a frame'}>
        ⛿ Save
      </button>
      <button type="button" className="sp-btn sp-hist-btn"
        onClick={() => { setSaveOpen(false); setHistOpen((o) => !o); void refresh(); }}
        title="Saved states — view or rerun from any of them">
        History{points.length ? ` (${points.length})` : ''} ▾
      </button>

      {saveOpen && (
        <div className="sp-pop sp-save-pop">
          <div className="sp-pop-h">Save this frame</div>
          <input className="sp-name" value={name} autoFocus
            onChange={(e) => setName(e.target.value)}
            placeholder="name this save-point"
            onKeyDown={(e) => { if (e.key === 'Enter') void doSave('local'); }} />
          <div className="sp-save-row">
            <button type="button" className="sp-save-where" disabled={busy}
              onClick={() => void doSave('local')} title="Private to this browser">
              ⬇ Browser
            </button>
            <button type="button" className="sp-save-where" disabled={busy}
              onClick={() => void doSave('server')} title="Persist to the workspace (shareable)">
              ⛁ Workspace
            </button>
          </div>
          {err && <div className="sp-err">{err}</div>}
        </div>
      )}

      {histOpen && (
        <div className="sp-pop sp-hist-pop">
          <div className="sp-pop-h">Save-points</div>
          {points.length === 0 ? (
            <div className="sp-empty">No save-points yet. Run, step to a frame, then ⛿ Save.</div>
          ) : (
            <ul className="sp-list">
              {points.map((p) => (
                <li className="sp-item" key={p.origin + ':' + p.id}>
                  <div className="sp-item-main">
                    <input type="checkbox" className="sp-pick" checked={sel.has(spKey(p))}
                      onChange={() => toggleSel(p)}
                      title="Include this snapshot in the exported series" />
                    <span className={'sp-origin sp-origin-' + p.origin}
                      title={p.origin === 'server' ? 'Workspace-persisted' : 'This browser'}>
                      {p.origin === 'server' ? '⛁' : '⬇'}
                    </span>
                    <span className="sp-item-name" title={p.name}>{p.name}</span>
                    <span className="sp-item-meta">
                      {p.frame != null ? `f${p.frame}${p.n_frames ? '/' + p.n_frames : ''}` : ''} · {ago(p.created_at)}
                    </span>
                  </div>
                  <div className="sp-item-actions">
                    <button type="button" onClick={() => { props.onView(p.state); setHistOpen(false); }}
                      title="Load this state into the graph">View</button>
                    <button type="button" className="sp-rerun"
                      onClick={() => { props.onRerun(p.state); setHistOpen(false); }}
                      title="Fork a new run starting from this state">↻ Rerun</button>
                    <button type="button" className="sp-del" onClick={() => void doDelete(p)}
                      title="Delete this save-point">✕</button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {points.length > 0 && (
            <div className="sp-export">
              <div className="sp-export-h">
                <span>Export series</span>
                <span className="sp-export-sel">
                  {sel.size} selected
                  <button type="button" className="sp-export-all"
                    onClick={() => setSel(new Set(sel.size === points.length ? [] : points.map(spKey)))}>
                    {sel.size === points.length ? 'none' : 'all'}
                  </button>
                </span>
              </div>
              <div className="sp-export-fmts">
                {(['png', 'svg', 'zip'] as SeriesFormat[]).map((f) => (
                  <label key={f} className="sp-export-fmt">
                    <input type="checkbox" checked={fmt.has(f)} onChange={() => toggleFmt(f)} />
                    {f.toUpperCase()}
                  </label>
                ))}
              </div>
              <button type="button" className="sp-export-btn"
                disabled={!!exporting || sel.size === 0 || fmt.size === 0}
                onClick={() => void doExport()}
                title="Render each selected snapshot and stitch them side-by-side">
                {exporting || `⤓ Export ${sel.size || ''} side-by-side`}
              </button>
              <div className="sp-export-note">
                Renders each selected snapshot in turn — the graph will cycle through them.
              </div>
              {err && <div className="sp-err">{err}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

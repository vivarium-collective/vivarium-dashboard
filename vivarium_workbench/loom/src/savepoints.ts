// src/savepoints.ts — run SAVE-POINTS: a full bigraph state captured at one
// frame of a run, named and kept so you can return to it later — View it (load
// the state back into the graph) or rerun-from it (fork a new run seeded with
// it, via startRun's seed_state).
//
// Two homes, chosen per-save: the browser (localStorage — private, instant,
// survives reloads) or the workspace (server endpoints — shareable, survives
// everything). listAll() merges both into one newest-first history.

export type SavePointOrigin = 'local' | 'server';

export interface SavePoint {
  id: string;
  composite_id: string;
  name: string;
  frame: number | null;
  n_frames?: number | null;
  created_at: number;                       // epoch seconds
  origin: SavePointOrigin;
  state: Record<string, unknown>;
}

export interface NewSavePoint {
  name: string;
  frame: number | null;
  n_frames?: number | null;
  state: Record<string, unknown>;
}

// ---- localStorage --------------------------------------------------------
const LKEY = (cid: string) => `bigraph-loom:savepoints:${cid}`;

function readLocal(cid: string): SavePoint[] {
  try {
    const raw = localStorage.getItem(LKEY(cid));
    const arr = raw ? (JSON.parse(raw) as SavePoint[]) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

function writeLocal(cid: string, points: SavePoint[]): void {
  try { localStorage.setItem(LKEY(cid), JSON.stringify(points)); } catch { /* quota / private mode */ }
}

export function listLocal(cid: string): SavePoint[] {
  return readLocal(cid).map((p) => ({ ...p, origin: 'local' as const }));
}

export function saveLocal(cid: string, sp: NewSavePoint): SavePoint {
  const rec: SavePoint = {
    id: (crypto.randomUUID?.() ?? String(Math.round(performance.now() * 1000))).slice(0, 12),
    composite_id: cid,
    name: sp.name.trim() || `frame ${sp.frame}`,
    frame: sp.frame,
    n_frames: sp.n_frames ?? null,
    created_at: Date.now() / 1000,
    origin: 'local',
    state: sp.state,
  };
  writeLocal(cid, [rec, ...readLocal(cid)]);
  return rec;
}

export function deleteLocal(cid: string, id: string): void {
  writeLocal(cid, readLocal(cid).filter((p) => p.id !== id));
}

// ---- server (workspace-persisted) ---------------------------------------
export async function listServer(cid: string): Promise<SavePoint[]> {
  try {
    const r = await fetch('/api/loom-savepoints?composite_id=' + encodeURIComponent(cid));
    if (!r.ok) return [];
    const body = await r.json();
    return (body.savepoints ?? []).map((p: SavePoint) => ({ ...p, origin: 'server' as const }));
  } catch { return []; }
}

export async function saveServer(cid: string, sp: NewSavePoint): Promise<SavePoint> {
  const r = await fetch('/api/loom-savepoint', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ composite_id: cid, ...sp }),
  });
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return { ...body, origin: 'server' as const };
}

export async function deleteServer(cid: string, id: string): Promise<void> {
  await fetch('/api/loom-savepoint?composite_id=' + encodeURIComponent(cid)
    + '&id=' + encodeURIComponent(id), { method: 'DELETE' });
}

// ---- unified -------------------------------------------------------------
export async function listAll(cid: string): Promise<SavePoint[]> {
  const [local, server] = await Promise.all([
    Promise.resolve(listLocal(cid)),
    listServer(cid),
  ]);
  return [...local, ...server].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
}

export function save(cid: string, where: SavePointOrigin, sp: NewSavePoint): Promise<SavePoint> {
  return where === 'server' ? saveServer(cid, sp) : Promise.resolve(saveLocal(cid, sp));
}

export function remove(cid: string, point: SavePoint): Promise<void> {
  if (point.origin === 'server') return deleteServer(cid, point.id);
  deleteLocal(cid, point.id);
  return Promise.resolve();
}

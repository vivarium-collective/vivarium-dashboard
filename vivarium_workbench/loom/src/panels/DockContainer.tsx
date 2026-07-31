// src/panels/DockContainer.tsx — left/right dockable panel zones around a canvas.
//
// Step 1 of the docking work: each panel can be collapsed (to a thin labeled
// edge tab) and docked to the LEFT or RIGHT edge via a ⇄ header button. Full
// drag-to-any-edge is a later step — there is no drag here.
//
// Placement + zone widths persist to one localStorage blob (global, not
// per-composite), so a reader's arrangement survives reloads. Multiple panels
// on the same side stack vertically, each with its own header + collapse toggle.
// The canvas fills the space between the two zones.

import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { clampSidebarWidth } from './filterHidden';

export type DockSide = 'left' | 'right';

export interface DockPanelSpec {
  id: string;
  title: string;
  /** Where the panel starts if the reader has no saved placement. */
  defaultSide: DockSide;
  /** Whether the panel starts collapsed if the reader has no saved placement. */
  defaultCollapsed?: boolean;
  /** Optional control rendered in the panel's header button bar, left of the
   *  dock (⇄) / collapse (‹) buttons — e.g. the Config panel's "⤢ Full". */
  headerAction?: React.ReactNode;
  /** Panel body. Called on every render, so it always sees fresh props. */
  render: () => React.ReactNode;
}

interface Placement { side: DockSide; collapsed: boolean; }

interface DockState {
  panels: Record<string, Placement>;
  widths: Record<DockSide, number>;
}

// v3: ALL dock panels (Processes, Inspector, Nodes) default collapsed so the
// graph gets the full width; bumping the key resets returning users to the new
// collapsed default instead of resurrecting a stale expanded blob.
const STORAGE_KEY = 'loom.dock.v3';
const DEFAULT_WIDTH = 300;

function lsGet(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
function lsSet(key: string, value: string): void {
  try { window.localStorage.setItem(key, value); } catch { /* ignore */ }
}

/** Seed placement from the specs, then overlay any persisted state (only for
 *  ids the specs still declare, so a stale blob can't resurrect a dead panel). */
function initialState(panels: DockPanelSpec[]): DockState {
  const base: DockState = {
    panels: {},
    widths: { left: DEFAULT_WIDTH, right: DEFAULT_WIDTH },
  };
  for (const p of panels) {
    base.panels[p.id] = { side: p.defaultSide, collapsed: !!p.defaultCollapsed };
  }
  const raw = lsGet(STORAGE_KEY);
  if (raw) {
    try {
      const saved = JSON.parse(raw) as Partial<DockState>;
      if (saved.panels) {
        for (const p of panels) {
          const s = saved.panels[p.id];
          if (s && (s.side === 'left' || s.side === 'right')) {
            base.panels[p.id] = { side: s.side, collapsed: !!s.collapsed };
          }
        }
      }
      if (saved.widths) {
        if (Number.isFinite(saved.widths.left)) {
          base.widths.left = clampSidebarWidth(saved.widths.left);
        }
        if (Number.isFinite(saved.widths.right)) {
          base.widths.right = clampSidebarWidth(saved.widths.right);
        }
      }
    } catch { /* ignore a corrupt blob — fall back to spec defaults */ }
  }
  return base;
}

export interface DockContainerProps {
  panels: DockPanelSpec[];
  children: React.ReactNode;
  /** Imperative "reveal this panel" signal: whenever `nonce` changes to a new
   *  value, the named panel is un-collapsed (brought into view) if it was
   *  collapsed. Lets a canvas click ensure the Inspector is visible. */
  expandRequest?: { id: string; nonce: number };
}

export function DockContainer({ panels, children, expandRequest }: DockContainerProps) {
  const [state, setState] = useState<DockState>(() => initialState(panels));

  useEffect(() => { lsSet(STORAGE_KEY, JSON.stringify(state)); }, [state]);

  // Reveal a panel on demand. Keyed on the nonce so re-clicking the SAME node
  // (nonce unchanged) doesn't fight a reader who just re-collapsed the panel.
  const reqNonce = expandRequest?.nonce ?? 0;
  const reqId = expandRequest?.id;
  useEffect(() => {
    if (!reqId || reqNonce <= 0) return;
    setState((s) => {
      const p = s.panels[reqId];
      if (!p || !p.collapsed) return s;
      return { ...s, panels: { ...s.panels, [reqId]: { ...p, collapsed: false } } };
    });
  }, [reqNonce, reqId]);

  const setSide = useCallback((id: string, side: DockSide) => {
    setState((s) => ({ ...s, panels: { ...s.panels, [id]: { ...s.panels[id], side } } }));
  }, []);
  const setCollapsed = useCallback((id: string, collapsed: boolean) => {
    setState((s) => ({ ...s, panels: { ...s.panels, [id]: { ...s.panels[id], collapsed } } }));
  }, []);
  const setWidth = useCallback((side: DockSide, width: number) => {
    setState((s) => ({ ...s, widths: { ...s.widths, [side]: clampSidebarWidth(width) } }));
  }, []);

  const forSide = (side: DockSide) => panels.filter((p) => (state.panels[p.id]?.side ?? p.defaultSide) === side);

  return (
    <div className="loom-dock" style={{ display: 'flex', flexDirection: 'row', width: '100%', height: '100%' }}>
      <DockZone
        side="left"
        specs={forSide('left')}
        state={state}
        width={state.widths.left}
        onSetSide={setSide}
        onSetCollapsed={setCollapsed}
        onSetWidth={setWidth}
      />
      <div className="loom-dock-center" style={{ flex: '1 1 0', minWidth: 0, position: 'relative', display: 'flex' }}>
        {children}
      </div>
      <DockZone
        side="right"
        specs={forSide('right')}
        state={state}
        width={state.widths.right}
        onSetSide={setSide}
        onSetCollapsed={setCollapsed}
        onSetWidth={setWidth}
      />
    </div>
  );
}

function DockZone(props: {
  side: DockSide;
  specs: DockPanelSpec[];
  state: DockState;
  width: number;
  onSetSide: (id: string, side: DockSide) => void;
  onSetCollapsed: (id: string, collapsed: boolean) => void;
  onSetWidth: (side: DockSide, width: number) => void;
}) {
  const { side, specs, state, width } = props;
  if (specs.length === 0) return null;

  const anyExpanded = specs.some((p) => !(state.panels[p.id]?.collapsed));
  const border = side === 'left'
    ? { borderRight: '1px solid #e5e7eb' }
    : { borderLeft: '1px solid #e5e7eb' };

  // --- drag-to-resize (only meaningful when at least one panel is expanded) --
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startWRef = useRef(0);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      const dx = e.clientX - startXRef.current;
      // Left zone: dragging right widens it. Right zone: dragging left widens it.
      const w = side === 'left' ? startWRef.current + dx : startWRef.current - dx;
      props.onSetWidth(side, w);
    };
    const onUp = () => {
      if (draggingRef.current) { draggingRef.current = false; document.body.style.cursor = ''; }
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [side, props]);
  const onHandleDown = (e: React.MouseEvent) => {
    draggingRef.current = true;
    startXRef.current = e.clientX;
    startWRef.current = width;
    document.body.style.cursor = 'col-resize';
    e.preventDefault();
  };

  return (
    <div
      className={`loom-dock-zone loom-dock-zone-${side}`}
      style={{
        position: 'relative',
        flex: '0 0 auto',
        width: anyExpanded ? width : undefined,
        display: 'flex', flexDirection: 'column',
        background: '#fff', ...border,
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      {anyExpanded && (
        <div
          className="loom-dock-resize"
          onMouseDown={onHandleDown}
          style={{
            position: 'absolute', top: 0, bottom: 0, width: 6, zIndex: 6,
            cursor: 'col-resize',
            ...(side === 'left' ? { right: -3 } : { left: -3 }),
          }}
        />
      )}
      {specs.map((spec) => {
        const placement = state.panels[spec.id] ?? { side: spec.defaultSide, collapsed: false };
        return placement.collapsed ? (
          <button
            key={spec.id}
            className="loom-dock-tab"
            title={`Expand ${spec.title}`}
            aria-label={`Expand ${spec.title}`}
            onClick={() => props.onSetCollapsed(spec.id, false)}
          >
            {spec.title}
          </button>
        ) : (
          <section key={spec.id} className="loom-dock-panel" style={{ flex: '1 1 0', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <header className="loom-dock-panel-header">
              <span className="loom-dock-panel-title">{spec.title}</span>
              <span className="loom-dock-panel-actions">
                {spec.headerAction}
                <button
                  type="button"
                  className="loom-dock-btn"
                  title={placement.side === 'left' ? 'Dock right' : 'Dock left'}
                  aria-label={`Dock ${spec.title} ${placement.side === 'left' ? 'right' : 'left'}`}
                  onClick={() => props.onSetSide(spec.id, placement.side === 'left' ? 'right' : 'left')}
                >
                  ⇄
                </button>
                <button
                  type="button"
                  className="loom-dock-btn"
                  title={`Collapse ${spec.title}`}
                  aria-label={`Collapse ${spec.title}`}
                  onClick={() => props.onSetCollapsed(spec.id, true)}
                >
                  {side === 'left' ? '‹' : '›'}
                </button>
              </span>
            </header>
            <div className="loom-dock-panel-body" style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
              {spec.render()}
            </div>
          </section>
        );
      })}
    </div>
  );
}

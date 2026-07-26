// src/panels/ProcessPanel.tsx — the consolidated process browser.
//
// Merges the two former process lists into one dockable panel:
//   - the old process-column ProcessRail (clustered, searchable, granularity
//     slider, pins, click-to-center-on-canvas), and
//   - the old right-sidebar "Processes" tab (per-process show/hide checkboxes +
//     "Show all").
//
// Crucially it computes its OWN clusters by calling affinity.clusterProcesses
// directly (the process-column layout that used to supply the `bands` is gone).
// The granularity slider therefore just re-groups this list — a cheap
// recomputation with NO canvas relayout — via hubFractionFor(granularity), the
// same mapping the retired layout used, so the default clustering is unchanged.

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Node } from '@xyflow/react';
import { clusterProcesses } from '../layouts/affinity';
import { subsystemClusters, locationClusters, type GroupAxis } from '../layouts/subsystem';
import { hubFractionFor, UNCLUSTERED_KEY } from '../layouts/processColumn';
import type { GroupBand } from '../layouts/types';
import type { UseFocus } from '../hooks/useFocus';
import { buildNestingTree } from '../layouts/nestingTree';
import { NestingTree } from './NestingTree';

export interface ProcessPanelProps {
  /** ALL React Flow nodes (pre-visibility-filter) so hidden processes are still
   *  listed and re-showable, and clustering sees the full inventory. */
  nodes: Node[];
  focus: UseFocus;
  /** Center/focus the canvas on a process picked in the panel. */
  onNavigate: (nodeId: string) => void;
  /** Currently-hidden node ids (drives the row show/hide checkboxes + the
   *  all-hidden-bucket collapse). */
  hidden: Set<string>;
  onToggleHidden: (id: string) => void;
  onShowAll: (kind: 'process' | 'store') => void;
  /** Root composite id — lets the tree lazily fetch a Composite Process's inner
   *  processes (fetchInnerComposite) so you can browse all the way down. */
  rootId?: string | null;
  /** Hops from the root generator to the CURRENT canvas level (non-empty only
   *  when drilled in), so lazy inner fetches key correctly. */
  hopsPrefix?: string[][];
}

/**
 * Group the process inventory into cluster bands for the list, along the chosen
 * axis:
 *   subsystem — biological function (subsystem.ts). Every process placed.
 *   connection — the store-affinity clusters (affinity.ts), plus a trailing
 *                "bookkeeping" bucket for the processes clusterProcesses filters
 *                out (listeners / allocators / *unique_update*).
 *   location  — the containing composite path (subsystem.ts). Every process placed.
 */
export function bandsFromNodes(
  nodes: Node[], axis: GroupAxis, granularity: number,
): GroupBand[] {
  let clusters;
  if (axis === 'subsystem') {
    clusters = subsystemClusters(nodes);
  } else if (axis === 'location') {
    clusters = locationClusters(nodes);
  } else {
    // connection: affinity clusters + a bookkeeping bucket for the leftovers
    // clusterProcesses drops (only this axis produces leftovers).
    const res = clusterProcesses(nodes, { hubFraction: hubFractionFor(granularity) });
    const clustered = new Set(res.clusters.flatMap((c) => c.processIds));
    const leftovers = nodes
      .filter((n) => n.type === 'process' && !clustered.has(n.id))
      .map((n) => n.id)
      .sort();
    clusters = leftovers.length
      ? [...res.clusters, { key: UNCLUSTERED_KEY, label: 'bookkeeping', processIds: leftovers }]
      : res.clusters;
  }
  return clusters
    .filter((c) => c.processIds.length > 0)
    .map((c) => ({
      key: c.key,
      label: c.label,
      yStart: 0,
      yEnd: 0,
      keyStoreId: null,
      nodeIds: [...c.processIds],
    }));
}

function lsGet(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
function lsSet(key: string, value: string): void {
  try { window.localStorage.setItem(key, value); } catch { /* ignore */ }
}
const pinStoreKey = (root: string | null | undefined) => `loom.pins.${root ?? '_'}`;
const nodeLabel = (n: Node): string => String((n.data as { label?: unknown })?.label ?? n.id);

export function ProcessPanel({
  nodes, focus, onNavigate, hidden, onToggleHidden, onShowAll, rootId, hopsPrefix,
}: ProcessPanelProps) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();

  // The containment tree — recomputed only when the inventory changes (NOT on
  // hover/selection: focus is threaded straight through to NestingTree).
  const tree = useMemo(() => buildNestingTree(nodes), [nodes]);

  const total = useMemo(
    () => nodes.filter((n) => n.type === 'process' || n.type === 'step').length,
    [nodes],
  );
  const orphanCount = useMemo(() => {
    let c = 0;
    const walk = (ns: typeof tree) => ns.forEach((t) => { if (t.isOrphan) c++; walk(t.children); });
    walk(tree);
    return c;
  }, [tree]);

  // Pinned ("preferred") processes float to the top. Persisted per-composite in
  // localStorage. Until the user pins anything for a composite, the DEFAULT pins
  // are its Composite Processes (the nested models worth quick access, e.g.
  // colony's cells) — so the important ones surface on top out of the box.
  const defaultPins = useMemo(
    () => nodes.filter((n) => (n.data as { isCompositeProcess?: unknown })?.isCompositeProcess === true)
      .map((n) => n.id),
    [nodes],
  );
  const [pins, setPins] = useState<Set<string>>(new Set());
  useEffect(() => {
    const raw = lsGet(pinStoreKey(rootId));
    if (raw != null) {
      try { setPins(new Set(JSON.parse(raw) as string[])); return; } catch { /* fall through */ }
    }
    setPins(new Set(defaultPins));
  }, [rootId, defaultPins]);

  const togglePin = useCallback((id: string) => {
    setPins((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      lsSet(pinStoreKey(rootId), JSON.stringify([...next]));
      return next;
    });
  }, [rootId]);

  const pinnedNodes = useMemo(
    () => nodes.filter(
      (n) => (n.type === 'process' || n.type === 'step')
        && pins.has(n.id)
        && (!q || nodeLabel(n).toLowerCase().includes(q)),
    ),
    [nodes, pins, q],
  );

  return (
    <div className="loom-process-rail">
      <input
        className="loom-rail-search"
        placeholder="Search processes…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="loom-rail-actions">
        <span className="loom-tree-summary">
          {total} process{total === 1 ? '' : 'es'}
          {orphanCount > 0 && <> · <span className="loom-badge-orphan-inline">{orphanCount} uncategorized</span></>}
        </span>
        <button type="button" className="loom-rail-link" onClick={() => onShowAll('process')}>Show all</button>
      </div>
      {pinnedNodes.length > 0 && (
        <div className="loom-tree-pinned">
          <div className="loom-tree-pinned-head">★ Pinned</div>
          {pinnedNodes.map((n) => {
            const id = n.id;
            const label = nodeLabel(n);
            const isHidden = hidden.has(id);
            return (
              <div
                key={'pin:' + id}
                className={`loom-tree-row loom-tree-leaf${focus.ctx.focused.has(id) ? ' is-active' : ''}${isHidden ? ' is-hidden' : ''}`}
                style={{ paddingLeft: 8 }}
                onMouseEnter={() => focus.hover(id)}
                onMouseLeave={() => focus.hover(null)}
                onClick={() => { focus.select(id); onNavigate(id); }}
                title={label}
              >
                <span className="loom-tree-caret loom-tree-caret-empty" />
                <input
                  type="checkbox" className="loom-tree-visible" checked={!isHidden}
                  title={isHidden ? 'Show on canvas' : 'Hide from canvas'} aria-label={`Toggle ${label}`}
                  onClick={(e) => e.stopPropagation()} onChange={() => onToggleHidden(id)}
                />
                <span className="loom-tree-name">{label}</span>
                <button
                  type="button" className="loom-tree-pin is-pinned"
                  title="Unpin" aria-pressed="true"
                  onClick={(e) => { e.stopPropagation(); togglePin(id); }}
                >★</button>
              </div>
            );
          })}
        </div>
      )}
      <div className="loom-rail-list">
        <NestingTree
          tree={tree}
          rootId={rootId ?? null}
          hopsPrefix={hopsPrefix ?? []}
          focus={focus}
          hiddenIds={hidden}
          pinnedIds={pins}
          onTogglePin={togglePin}
          onToggleHidden={onToggleHidden}
          onNavigate={onNavigate}
          query={q}
        />
      </div>
    </div>
  );
}

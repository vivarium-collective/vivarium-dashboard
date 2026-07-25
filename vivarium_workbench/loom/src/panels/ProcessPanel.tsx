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

import { useEffect, useMemo, useState } from 'react';
import type { Node } from '@xyflow/react';
import { clusterProcesses } from '../layouts/affinity';
import { subsystemClusters, locationClusters, type GroupAxis } from '../layouts/subsystem';
import { hubFractionFor, DEFAULT_GRANULARITY, UNCLUSTERED_KEY } from '../layouts/processColumn';
import type { GroupBand } from '../layouts/types';
import type { UseFocus } from '../hooks/useFocus';
import { ProcessRail } from './ProcessRail';

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
}

const GRANULARITY_KEY = 'loom.process-panel.granularity';
const GROUP_AXIS_KEY = 'loom.process-panel.group-axis';

function readGroupAxis(): GroupAxis {
  const raw = lsGet(GROUP_AXIS_KEY);
  return raw === 'connection' || raw === 'location' || raw === 'subsystem' ? raw : 'subsystem';
}

function lsGet(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
function lsSet(key: string, value: string): void {
  try { window.localStorage.setItem(key, value); } catch { /* ignore */ }
}

function readGranularity(): number {
  const raw = lsGet(GRANULARITY_KEY);
  const n = raw != null ? Number(raw) : NaN;
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : DEFAULT_GRANULARITY;
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

export function ProcessPanel({
  nodes, focus, onNavigate, hidden, onToggleHidden, onShowAll,
}: ProcessPanelProps) {
  // Granularity only tunes the CONNECTION axis's hub cutoff; the slider was
  // retired (grouping is automatic), so it stays at the persisted/default value.
  const [granularity] = useState<number>(() => readGranularity());
  const [groupAxis, setGroupAxis] = useState<GroupAxis>(() => readGroupAxis());
  useEffect(() => { lsSet(GROUP_AXIS_KEY, groupAxis); }, [groupAxis]);

  // Recompute clusters only when the inventory, axis, or granularity changes —
  // NOT on canvas hover/selection (focus is threaded straight through to
  // ProcessRail, which memoizes its own per-hover work).
  const bands = useMemo(
    () => bandsFromNodes(nodes, groupAxis, granularity),
    [nodes, groupAxis, granularity],
  );

  return (
    <ProcessRail
      bands={bands}
      nodes={nodes}
      focus={focus}
      groupAxis={groupAxis}
      onGroupAxisChange={setGroupAxis}
      onNavigate={onNavigate}
      hiddenIds={hidden}
      onToggleHidden={onToggleHidden}
      onShowAll={() => onShowAll('process')}
    />
  );
}

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
 * Group the process inventory into cluster bands for the list. Mirrors the
 * former processColumnMode.run band construction (minus canvas geometry): the
 * affinity clusters, plus a trailing "bookkeeping" bucket for the processes
 * clusterProcesses filters out (listeners / allocators / *unique_update*).
 */
export function bandsFromNodes(nodes: Node[], granularity: number): GroupBand[] {
  const { clusters } = clusterProcesses(nodes, { hubFraction: hubFractionFor(granularity) });
  const clustered = new Set(clusters.flatMap((c) => c.processIds));
  const leftovers = nodes
    .filter((n) => n.type === 'process' && !clustered.has(n.id))
    .map((n) => n.id)
    .sort();
  const groups = leftovers.length
    ? [...clusters, { key: UNCLUSTERED_KEY, label: 'bookkeeping', processIds: leftovers }]
    : clusters;
  return groups
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
  const [granularity, setGranularity] = useState<number>(() => readGranularity());
  useEffect(() => { lsSet(GRANULARITY_KEY, String(granularity)); }, [granularity]);

  // Recompute clusters only when the inventory or granularity changes — NOT on
  // canvas hover/selection (focus is threaded straight through to ProcessRail,
  // which memoizes its own per-hover work).
  const bands = useMemo(
    () => bandsFromNodes(nodes, granularity),
    [nodes, granularity],
  );

  return (
    <ProcessRail
      bands={bands}
      nodes={nodes}
      focus={focus}
      granularity={granularity}
      onGranularityChange={setGranularity}
      onNavigate={onNavigate}
      hiddenIds={hidden}
      onToggleHidden={onToggleHidden}
      onShowAll={() => onShowAll('process')}
    />
  );
}

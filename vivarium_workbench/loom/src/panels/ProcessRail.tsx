// src/panels/ProcessRail.tsx — browse the process inventory by group.
//
// The list groups processes along a chosen AXIS (subsystem / connection /
// location — see subsystem.ts + affinity.ts), names every group, and lets a
// reader search, jump, collapse, keep-open, and show/hide. It drives the SAME
// focus state the canvas culls edges by, so the two stay in sync.
//
// Three distinct affordances, one job each (this replaced an overloaded "pin"):
//   - checkbox    → show / hide the process on the canvas
//   - row click   → focus it + centre the canvas on it (opens its card)
//   - keep-open ★ → keep that card at full detail regardless of zoom
//
// Performance note: the rail re-renders on every canvas hover (focus.ctx
// changes identity when hover/selection moves). So the expensive derivations —
// the id→label map and the search-filtered band list — memoize on genuinely
// stable inputs (nodes, bands, query, hiddenIds), NEVER on focus.ctx.

import { useCallback, useMemo, useState } from 'react';
import type { Node } from '@xyflow/react';
import type { GroupBand } from '../layouts/types';
import type { GroupAxis } from '../layouts/subsystem';
import type { UseFocus } from '../hooks/useFocus';

export interface ProcessRailProps {
  bands: GroupBand[];
  nodes: Node[];
  focus: UseFocus;
  /** The active grouping axis, and its setter (drives the Group-by selector). */
  groupAxis: GroupAxis;
  onGroupAxisChange: (axis: GroupAxis) => void;
  onNavigate: (nodeId: string) => void;
  /**
   * Node ids currently hidden from the canvas. A group whose every member is
   * hidden collapses by default (named + counted, not listed as if on-canvas).
   * Optional — treated as "nothing hidden" when omitted.
   */
  hiddenIds?: Set<string>;
  /**
   * When provided, each row carries a show/hide checkbox for that process's
   * canvas visibility. Omitted → the rail is list-only.
   */
  onToggleHidden?: (id: string) => void;
  /** With onToggleHidden, a "Show all" affordance un-hides every process. */
  onShowAll?: () => void;
}

const EMPTY: Set<string> = new Set();

const AXES: { id: GroupAxis; label: string; hint: string }[] = [
  { id: 'subsystem',  label: 'Subsystem',  hint: 'Group by biological function (transcription, translation, …)' },
  { id: 'connection', label: 'Connection', hint: 'Group by the store processes share (bulk, unique.RNA, …)' },
  { id: 'location',   label: 'Location',   hint: 'Group by the composite each process lives in' },
];

export function ProcessRail({
  bands, nodes, focus, groupAxis, onGroupAxisChange, onNavigate,
  hiddenIds = EMPTY, onToggleHidden, onShowAll,
}: ProcessRailProps) {
  const [query, setQuery] = useState('');
  // Per-band manual expand/collapse override, keyed by band.key. Absent = use
  // the band's default (collapsed only when every member is hidden).
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});

  const labelById = useMemo(() => {
    const m = new Map<string, string>();
    for (const n of nodes) m.set(n.id, String((n.data as { label?: unknown })?.label ?? n.id));
    return m;
  }, [nodes]);

  const q = query.trim().toLowerCase();

  // The bookkeeping bucket (key starts with '~') whose members are ALL hidden
  // collapses by default — named and counted, but not dumping its off-canvas
  // rows among the visible ones. A REAL group the user happened to hide still
  // lists its rows (marked hidden): they hid it explicitly and expect to see it.
  // Every group is collapsible via click regardless; this only sets the DEFAULT.
  const isDefaultCollapsed = useCallback(
    (band: GroupBand) =>
      band.key.startsWith('~')
      && band.nodeIds.length > 0
      && band.nodeIds.every((id) => hiddenIds.has(id)),
    [hiddenIds],
  );

  // Search-filter each band; drop bands with no surviving members. Memoized on
  // stable inputs only (never focus.ctx) so a hover does not re-filter.
  const filtered = useMemo(
    () => bands
      .map((band) => ({
        band,
        ids: band.nodeIds.filter(
          (id) => !q || (labelById.get(id) ?? id).toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.ids.length > 0),
    [bands, q, labelById],
  );

  const searching = q.length > 0;
  const setAll = (expanded: boolean) =>
    setOverrides(Object.fromEntries(bands.map((b) => [b.key, expanded])));

  return (
    <div className="loom-process-rail">
      <input
        className="loom-rail-search"
        placeholder="Search processes…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {/* Group-by axis selector. */}
      <div className="loom-rail-groupby" role="tablist" aria-label="Group processes by">
        <span className="loom-rail-groupby-label">Group by</span>
        {AXES.map((a) => (
          <button
            key={a.id}
            type="button"
            role="tab"
            aria-selected={groupAxis === a.id}
            title={a.hint}
            className={`loom-rail-axis${groupAxis === a.id ? ' is-active' : ''}`}
            onClick={() => onGroupAxisChange(a.id)}
          >
            {a.label}
          </button>
        ))}
      </div>

      <div className="loom-rail-actions">
        <button type="button" className="loom-rail-link" onClick={() => setAll(true)}>Expand all</button>
        <button type="button" className="loom-rail-link" onClick={() => setAll(false)}>Collapse all</button>
        {onShowAll && onToggleHidden && (
          <button type="button" className="loom-rail-link" onClick={onShowAll}>Show all</button>
        )}
      </div>

      <div className="loom-rail-list">
        {filtered.map(({ band, ids }) => {
          // Searching always reveals matches, even inside a collapsed group.
          const expanded = searching
            || (overrides[band.key] ?? !isDefaultCollapsed(band));
          return (
            <div key={band.key} className="loom-rail-cluster">
              <div
                className="loom-cluster-band loom-rail-cluster-label is-collapsible"
                onClick={() => setOverrides((o) => ({ ...o, [band.key]: !expanded }))}
                role="button"
                aria-expanded={expanded}
              >
                <span className="loom-rail-caret">{expanded ? '▾' : '▸'}</span>
                <span className="loom-rail-cluster-name">{band.label}</span>
                <span className="loom-rail-count">{band.nodeIds.length}</span>
              </div>
              {expanded && ids.map((id) => {
                const focused = focus.ctx.focused.has(id);
                const keptOpen = focus.keptOpen.has(id);
                const hidden = hiddenIds.has(id);
                const cls = 'loom-rail-row'
                  + (focused || keptOpen ? ' is-active' : '')
                  + (hidden ? ' is-hidden' : '');
                return (
                  <div
                    key={id}
                    className={cls}
                    onMouseEnter={() => focus.hover(id)}
                    onMouseLeave={() => focus.hover(null)}
                    onClick={() => { focus.select(id); onNavigate(id); }}
                  >
                    {onToggleHidden && (
                      <input
                        type="checkbox"
                        className="loom-rail-visible"
                        checked={!hidden}
                        title={hidden ? 'Show on canvas' : 'Hide from canvas'}
                        aria-label={`Toggle ${labelById.get(id) ?? id}`}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => onToggleHidden(id)}
                      />
                    )}
                    <span className="loom-rail-row-label">{labelById.get(id) ?? id}</span>
                    <button
                      type="button"
                      className={`loom-rail-keepopen${keptOpen ? ' is-open' : ''}`}
                      title={keptOpen ? 'Stop keeping open' : 'Keep card open (full detail)'}
                      aria-pressed={keptOpen}
                      onClick={(e) => { e.stopPropagation(); focus.toggleKeepOpen(id); }}
                    >
                      {keptOpen ? '★' : '☆'}
                    </button>
                  </div>
                );
              })}
              {!expanded && (
                <div className="loom-rail-collapsed-note">
                  {band.nodeIds.length}{' '}
                  {band.nodeIds.every((id) => hiddenIds.has(id)) ? 'hidden' : 'processes'}
                </div>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && <div className="loom-rail-empty">No matching processes</div>}
      </div>
    </div>
  );
}

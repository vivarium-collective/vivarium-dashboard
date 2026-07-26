// @vitest-environment jsdom
//
// ProcessPanel is the consolidated process browser: the clustered/searchable
// rail (with pins + click-to-center) merged with the old sidebar "Processes"
// tab's show/hide checkboxes. It computes its OWN clusters via
// affinity.clusterProcesses (the process-column layout is gone), so the
// granularity slider re-groups the list with no canvas involvement.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import type { Node } from '@xyflow/react';
import { ProcessPanel, bandsFromNodes } from '../panels/ProcessPanel';
import { clusterProcesses } from '../layouts/affinity';
import { hubFractionFor, UNCLUSTERED_KEY } from '../layouts/processColumn';

afterEach(cleanup);

// Two processes that share a store 's.shared' (so they cluster together) plus a
// bookkeeping process (a *listener*, which clusterProcesses filters out → it
// lands in the trailing "bookkeeping" bucket). A store node is present too, so
// the panel proves it lists only processes.
function proc(id: string, targets: Record<string, string>): Node {
  return {
    id, type: 'process', position: { x: 0, y: 0 },
    data: {
      label: id, address: 'local:test', path: ['top', id],
      inputPortsTarget: targets, outputPortsTarget: {},
    },
  } as unknown as Node;
}

const NODES: Node[] = [
  proc('alpha', { a: 'top.shared', b: 'top.shared' }),
  proc('beta', { a: 'top.shared' }),
  proc('mass_listener', { a: 'top.mass' }),
  { id: 'top.shared', type: 'store', position: { x: 0, y: 0 }, data: { label: 'shared', path: ['top', 'shared'] } } as unknown as Node,
];

function makeFocus(over: Record<string, unknown> = {}) {
  return {
    hovered: null, selected: null, pinned: new Set<string>(), keptOpen: new Set<string>(),
    hover: vi.fn(), select: vi.fn(), togglePin: vi.fn(), toggleKeepOpen: vi.fn(),
    clear: vi.fn(), prunePins: vi.fn(),
    ctx: { focused: new Set<string>(), pinned: new Set<string>() },
    ...over,
  };
}

function setup(over: Partial<React.ComponentProps<typeof ProcessPanel>> = {}) {
  const onNavigate = vi.fn();
  const onToggleHidden = vi.fn();
  const onShowAll = vi.fn();
  const focus = makeFocus();
  const utils = render(
    <ProcessPanel
      nodes={NODES}
      focus={focus as never}
      onNavigate={onNavigate}
      hidden={new Set()}
      onToggleHidden={onToggleHidden}
      onShowAll={onShowAll}
      {...over}
    />,
  );
  return { onNavigate, onToggleHidden, onShowAll, focus, ...utils };
}

describe('bandsFromNodes (clusters straight from affinity.clusterProcesses)', () => {
  it('groups by shared store and adds a bookkeeping bucket for filtered processes', () => {
    const bands = bandsFromNodes(NODES, 'connection', 0.5);
    // The two shared-store processes cluster together...
    const shared = bands.find((b) => b.nodeIds.includes('alpha'));
    expect(shared).toBeTruthy();
    expect(shared!.nodeIds).toEqual(['alpha', 'beta']);
    // ...and the *listener* (dropped by clusterProcesses) lands in bookkeeping.
    const book = bands.find((b) => b.key === UNCLUSTERED_KEY);
    expect(book).toBeTruthy();
    expect(book!.nodeIds).toEqual(['mass_listener']);
    // No store node ever appears in a band.
    expect(bands.flatMap((b) => b.nodeIds)).not.toContain('top.shared');
  });

  it('is exactly clusterProcesses at the mapped hubFraction plus leftovers', () => {
    const g = 0.7;
    const { clusters } = clusterProcesses(NODES, { hubFraction: hubFractionFor(g) });
    const bands = bandsFromNodes(NODES, 'connection', g);
    // Every real (non-bookkeeping) band mirrors a clusterProcesses cluster.
    for (const c of clusters) {
      const b = bands.find((x) => x.key === c.key);
      expect(b).toBeTruthy();
      expect(b!.nodeIds).toEqual(c.processIds);
    }
  });
});

describe('ProcessPanel (nesting tree)', () => {
  it('renders every process under its containing group, never a store row', () => {
    setup();
    expect(screen.getByText('alpha')).toBeTruthy();
    expect(screen.getByText('beta')).toBeTruthy();
    // The containing composite path segment becomes a group header...
    expect(screen.getByText('top', { selector: '.loom-tree-name' })).toBeTruthy();
    // ...and the store node itself is never listed as a process.
    expect(screen.queryByText('top.shared')).toBeNull();
    expect(screen.queryByText('shared')).toBeNull();
  });

  it('flags uncategorized processes and counts them', () => {
    setup();
    // alpha/beta match no subsystem → uncategorized; mass_listener → Observation.
    // Two per-row badges + the header summary ("N uncategorized").
    expect(screen.getAllByText('uncategorized').length).toBe(2);
    expect(screen.getByText(/2 uncategorized/)).toBeTruthy();
  });

  it('filters processes by the search box', () => {
    setup();
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'alph' } });
    expect(screen.queryByText('alpha')).toBeTruthy();
    expect(screen.queryByText('beta')).toBeNull();
  });

  it('navigates and selects when a process row is clicked', () => {
    const { onNavigate, focus } = setup();
    fireEvent.click(screen.getByText('alpha'));
    expect(onNavigate).toHaveBeenCalledWith('alpha');
    expect(focus.select).toHaveBeenCalledWith('alpha');
  });

  it('toggles a process\'s canvas visibility from its row checkbox', () => {
    const { onToggleHidden } = setup();
    const row = screen.getByText('alpha').closest('.loom-tree-row') as HTMLElement;
    const checkbox = within(row).getByRole('checkbox');
    fireEvent.click(checkbox);
    expect(onToggleHidden).toHaveBeenCalledWith('alpha');
  });

  it('un-hides everything via "Show all"', () => {
    const { onShowAll } = setup({ hidden: new Set(['alpha']) });
    fireEvent.click(screen.getByRole('button', { name: /show all/i }));
    expect(onShowAll).toHaveBeenCalledWith('process');
  });

  it('pins a process to the top via its ☆ star', () => {
    setup();
    // No Pinned section initially (no composite processes → no default pins).
    expect(screen.queryByText('★ Pinned')).toBeNull();
    // Click alpha's pin star (first matching star row).
    const row = screen.getByText('alpha').closest('.loom-tree-row') as HTMLElement;
    fireEvent.click(within(row).getByTitle('Pin to top'));
    // Pinned section appears with alpha in it.
    const pinned = screen.getByText('★ Pinned').closest('.loom-tree-pinned') as HTMLElement;
    expect(within(pinned).getByText('alpha')).toBeTruthy();
  });

  it('default-pins Composite Processes on first load', () => {
    const withComposite: Node[] = [
      ...NODES,
      { id: 'top.cell', type: 'process', position: { x: 0, y: 0 },
        data: { label: 'cell', path: ['top', 'cell'], isCompositeProcess: true } } as unknown as Node,
    ];
    setup({ nodes: withComposite, rootId: 'ws.demo.first-load' });
    const pinned = screen.getByText('★ Pinned').closest('.loom-tree-pinned') as HTMLElement;
    expect(within(pinned).getByText('cell')).toBeTruthy();
  });
});

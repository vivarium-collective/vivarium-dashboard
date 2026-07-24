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
    hovered: null, selected: null, pinned: new Set<string>(),
    hover: vi.fn(), select: vi.fn(), togglePin: vi.fn(),
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
    const bands = bandsFromNodes(NODES, 0.5);
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
    const bands = bandsFromNodes(NODES, g);
    // Every real (non-bookkeeping) band mirrors a clusterProcesses cluster.
    for (const c of clusters) {
      const b = bands.find((x) => x.key === c.key);
      expect(b).toBeTruthy();
      expect(b!.nodeIds).toEqual(c.processIds);
    }
  });
});

describe('ProcessPanel', () => {
  it('renders clustered processes under their cluster label', () => {
    setup();
    expect(screen.getByText('alpha')).toBeTruthy();
    expect(screen.getByText('beta')).toBeTruthy();
    // Grouped under the shared-store cluster band...
    const band = screen.getByText('shared', { selector: '.loom-rail-cluster-label' });
    expect(band).toBeTruthy();
    // ...and no process ROW exists for the store node itself (store exclusion is
    // proven structurally in bandsFromNodes above).
    expect(screen.queryByText('top.shared')).toBeNull();
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

  it('focuses the process on row click so its wires highlight (focusReveals)', () => {
    // Row click routes through useFocus.select — the SAME focus the cluster-grid
    // edgeVisibility reveals + highlights a process's wires by. So clicking a
    // panel row lights up that process's wiring on the canvas at any zoom.
    const { focus } = setup();
    fireEvent.click(screen.getByText('beta'));
    expect(focus.select).toHaveBeenCalledWith('beta');
  });

  it('toggles a process\'s canvas visibility from its row checkbox', () => {
    const { onToggleHidden } = setup();
    const row = screen.getByText('alpha').closest('.loom-rail-row') as HTMLElement;
    const checkbox = within(row).getByRole('checkbox');
    fireEvent.click(checkbox);
    expect(onToggleHidden).toHaveBeenCalledWith('alpha');
  });

  it('un-hides everything via "Show all"', () => {
    const { onShowAll } = setup({ hidden: new Set(['alpha']) });
    fireEvent.click(screen.getByRole('button', { name: /show all/i }));
    expect(onShowAll).toHaveBeenCalledWith('process');
  });

  it('groups automatically (by connections) with no granularity slider', () => {
    setup();
    // Grouping is automatic — there is no granularity control — and every
    // process still renders under its auto-derived cluster.
    expect(screen.queryByLabelText(/granularity/i)).toBeNull();
    expect(screen.getByText('alpha')).toBeTruthy();
    expect(screen.getByText('beta')).toBeTruthy();
  });

  it('pins from a row without navigating', () => {
    const { focus, onNavigate } = setup();
    fireEvent.click(screen.getAllByTitle('Pin')[0]);
    expect(focus.togglePin).toHaveBeenCalled();
    expect(onNavigate).not.toHaveBeenCalled();
  });
});

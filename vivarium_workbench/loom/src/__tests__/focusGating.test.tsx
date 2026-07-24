// @vitest-environment jsdom
//
// App-level tests for the cluster-grid graph's focus handling. The sole canvas
// layout is now FOCUS-DRIVEN (clusterGridMode.focusReveals === true): the
// default view keeps the hub-hidden declutter, and focusing a process — by
// hover OR by click — reveals + highlights ALL its wires (hub wires included).
// So App wires up onNodeMouseEnter/Leave, renders the focus hint, and prunes
// pins. `focus.clear()` still runs on every composite:load.
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act, within } from '@testing-library/react';
import App from '../App';

// The Process panel lists each process by the same label the canvas node shows,
// so a bare screen.getByText('p1') is ambiguous. These tests are about the
// CANVAS node's focus behavior, so scope the query to the canvas column (the
// panels are siblings, outside .loom-canvas).
const canvas = () => within(document.querySelector('.loom-canvas') as HTMLElement);

beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

afterEach(() => {
  cleanup();
  window.history.pushState({}, '', '/');
});

function postCompositeLoad(state: unknown, metadata: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new MessageEvent('message', {
      data: { type: 'composite:load', state, metadata },
    }));
  });
}

/** One process ('p1') wired to one store ('s1') — enough for both a real
 *  process-node DOM element and a real wire edge to exist. */
const ONE_PROCESS_STATE = {
  state: {
    p1: { _type: 'process', address: 'local:test', inputs: { a: ['s1'] }, outputs: {} },
    s1: 5,
  },
};

async function loadOntoWiringTab(metadata: Record<string, unknown>) {
  // static=1 disables onlyRenderVisibleElements, so nodes render regardless
  // of jsdom's zero-size viewport.
  window.history.pushState({}, '', '?static=1');
  render(<App />);
  postCompositeLoad(ONE_PROCESS_STATE, metadata);
  fireEvent.click(screen.getByRole('button', { name: /^Explore$/i }));
  // Scope the wait to the canvas so this doesn't throw on the Process panel's
  // matching 'p1' row.
  const label = await canvas().findByText('p1');
  return label;
}

describe('cluster-grid graph — App focus wiring', () => {
  it('is focus-driven: shows the focus hint and highlights on click', async () => {
    render(<App />);
    window.history.pushState({}, '', '?static=1');
    postCompositeLoad(ONE_PROCESS_STATE, { id: 'test.composites.hover-a', name: 'hover-a' });
    fireEvent.click(screen.getByRole('button', { name: /^Explore$/i }));
    await canvas().findByText('p1');

    // Focus-driven mode → the focus hint is present, prompting interaction.
    const hint = document.querySelector('.loom-focus-hint');
    expect(hint).not.toBeNull();
    expect(hint?.textContent).toMatch(/highlight its wiring/i);

    // Clicking a canvas process focuses it → the hint reports it as highlighted.
    fireEvent.click(canvas().getByText('p1'));
    expect(document.querySelector('.loom-focus-hint')?.textContent)
      .toMatch(/highlighting wiring for 1 node/i);
  });

  it('stamps the semantic-zoom tier onto its cards', async () => {
    await loadOntoWiringTab({ id: 'test.composites.tier-h', name: 'tier-h' });
    // A stamped tier makes ProcessNode render its tiered body (class
    // `process-node-<tier>`); the initial tier is 'ports'. The legacy untiered
    // card has only `.process-node` with no tier suffix — so this class existing
    // is proof tieredNodes stamps `_tier` in hierarchy mode.
    expect(document.querySelector('.process-node-ports')).not.toBeNull();
  });
});

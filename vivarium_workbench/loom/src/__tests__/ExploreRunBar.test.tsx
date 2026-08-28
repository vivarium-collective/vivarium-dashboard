// @vitest-environment jsdom
// Tests for the Explore run bar's Stop control: while a run is live a "■ Stop"
// button appears, and clicking it POSTs to the run's /stop endpoint (the worker
// is SIGTERM'd server-side; the partial trajectory is kept). Drives the run via
// the hook's re-attach path (an active run recorded in sessionStorage) so the
// bar mounts straight into a "running" state without the click-Run + timer dance.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { ExploreRunBar } from '../panels/ExploreRunBar';

const ACTIVE_RUN_KEY = 'bigraph-loom:active-run';
const COMPOSITE_ID = 'some.composite.id';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

/** Route fetch by URL: status → running, trajectory → empty, stop → signalled. */
function mockRoutes() {
  const spy = vi.fn((url: string, _init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/status')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => ({
        run_id: 'r-1', status: 'running', progress_step: 3, n_steps: 10,
      }) });
    }
    if (u.endsWith('/stop')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => ({
        run_id: 'r-1', outcome: 'signalled', status: 'cancelled',
      }) });
    }
    // trajectory (…/composite-run/r-1)
    return Promise.resolve({ ok: true, status: 200, json: async () => ({
      run_id: 'r-1', trajectory: [],
    }) });
  });
  vi.stubGlobal('fetch', spy as unknown as typeof fetch);
  return spy;
}

const BASE_PROPS = {
  compositeId: COMPOSITE_ID,
  overrides: {},
  emitSet: new Set<string>(),
};

describe('ExploreRunBar Stop control', () => {
  beforeEach(() => {
    sessionStorage.setItem(ACTIVE_RUN_KEY, JSON.stringify({
      run_id: 'r-1', composite_id: COMPOSITE_ID,
    }));
  });

  it('shows a Stop button while running and POSTs to /stop on click', async () => {
    const spy = mockRoutes();
    render(<ExploreRunBar {...BASE_PROPS} />);

    // The re-attach effect polls status → running → the Stop button appears.
    const stopBtn = await screen.findByRole('button', { name: /Stop/i });
    expect(stopBtn).toBeTruthy();

    fireEvent.click(stopBtn);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        '/api/composite-run/r-1/stop',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    // Optimistic feedback: the button reads "Stopping…" until a terminal poll.
    expect(screen.getByRole('button', { name: /Stopping/i })).toBeTruthy();
  });

  it('shows no Stop button when idle (no active run)', () => {
    sessionStorage.clear();
    mockRoutes();
    render(<ExploreRunBar {...BASE_PROPS} />);
    expect(screen.queryByRole('button', { name: /Stop/i })).toBeNull();
  });
});

// @vitest-environment jsdom
// Tests for ConfigPanel's "external config" input mode (item 86): upload or
// paste a JSON document, matched server-side onto the composite's own
// declared params via POST /api/composite-config-translate, then applied
// into the SAME per-field form state the existing Apply button already uses.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { ConfigPanel } from '../panels/ConfigPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// Synthetic fixture shaped like a real translate response — no
// usecase-identifying content, per this repo's standing convention.
const PARAMS = {
  n_cells: { type: 'int' as const, default: 2, description: 'cell count' },
  injected_processes: { type: 'map' as const, default: {}, description: 'fork spec' },
};

const BASE_PROPS = {
  compositeId: 'some.composite.id',
  overrides: {},
  onApplied: () => {},
};

function mockTranslateFetch(response: unknown, ok = true) {
  const fetchSpy = vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 422,
    json: async () => response,
  });
  vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch);
  return fetchSpy;
}

describe('ConfigPanel external config', () => {
  it('toggle reveals the panel, hidden by default', () => {
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} />);
    expect(screen.queryByPlaceholderText(/matched against this composite/i)).toBeNull();
    fireEvent.click(screen.getByText('📄 External config'));
    expect(screen.getByPlaceholderText(/matched against this composite/i)).toBeTruthy();
  });

  it('applies a valid JSON document into the matching per-field inputs', async () => {
    const fetchSpy = mockTranslateFetch({
      params: { n_cells: 7, injected_processes: { fork_repo: 'https://example.invalid/x.git' } },
      unmatched: [],
    });
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} />);
    fireEvent.click(screen.getByText('📄 External config'));
    const box = screen.getByPlaceholderText(/matched against this composite/i);
    fireEvent.change(box, { target: { value: '{"n_cells":7,"fork_repo":"https://example.invalid/x.git"}' } });
    fireEvent.click(screen.getByText('Apply config'));

    await waitFor(() => expect(screen.getByText(/set 2 field/i)).toBeTruthy());
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/composite-config-translate',
      expect.objectContaining({ method: 'POST' }),
    );
    const nCellsInput = document.getElementById('explore-cfg-n_cells') as HTMLInputElement;
    expect(nCellsInput.value).toBe('7');
    const injectedInput = document.getElementById('explore-cfg-injected_processes') as HTMLInputElement;
    expect(JSON.parse(injectedInput.value)).toEqual({ fork_repo: 'https://example.invalid/x.git' });
  });

  it('reports unmatched keys without failing', async () => {
    mockTranslateFetch({ params: { n_cells: 3 }, unmatched: ['totally_unknown_key'] });
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} />);
    fireEvent.click(screen.getByText('📄 External config'));
    const box = screen.getByPlaceholderText(/matched against this composite/i);
    fireEvent.change(box, { target: { value: '{"n_cells":3,"totally_unknown_key":1}' } });
    fireEvent.click(screen.getByText('Apply config'));
    await waitFor(() => expect(screen.getByText(/totally_unknown_key/)).toBeTruthy());
  });

  it('shows a client-side error for invalid JSON without calling the server', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch);
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} />);
    fireEvent.click(screen.getByText('📄 External config'));
    const box = screen.getByPlaceholderText(/matched against this composite/i);
    fireEvent.change(box, { target: { value: '{not valid json' } });
    fireEvent.click(screen.getByText('Apply config'));
    await waitFor(() => expect(document.querySelector('.cfg-error')).toBeTruthy());
    expect(document.querySelector('.cfg-error')!.textContent).toMatch(/not valid json/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('readOnly disables the external-config toggle', () => {
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} readOnly />);
    const btn = screen.getByText('📄 External config') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

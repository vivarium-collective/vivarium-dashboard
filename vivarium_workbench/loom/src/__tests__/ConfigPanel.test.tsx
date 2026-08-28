// @vitest-environment jsdom
// Tests for ConfigPanel's unified Fields⇄JSON editor (config + inputs share the
// same affordance) and the collapsible input tree. The JSON mode reuses the
// external-config translate path (item 86): edit/paste a JSON document, matched
// server-side onto the composite's declared params, then resolved on Apply.
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

/** Route fetch by URL so a JSON-mode Apply (translate → resolve) can be mocked. */
function mockRoutes({ translate, resolve }: { translate?: unknown; resolve?: unknown }) {
  const spy = vi.fn((url: string) => {
    const u = String(url);
    if (u.includes('/api/composite-config-translate')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => translate });
    }
    if (u.includes('/api/composite-resolve')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => resolve });
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  });
  vi.stubGlobal('fetch', spy as unknown as typeof fetch);
  return spy;
}

describe('ConfigPanel — Configure Fields⇄JSON parity', () => {
  it('defaults to Fields mode; the JSON toggle reveals the editable document', () => {
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} />);
    // Fields mode: per-field inputs present, no JSON textarea.
    expect(document.getElementById('explore-cfg-n_cells')).toBeTruthy();
    expect(screen.queryByPlaceholderText(/matched onto this composite/i)).toBeNull();
    // Switch to JSON: textarea appears, fields gone.
    fireEvent.click(screen.getByRole('tab', { name: /JSON/ }));
    expect(screen.getByPlaceholderText(/matched onto this composite/i)).toBeTruthy();
    expect(document.getElementById('explore-cfg-n_cells')).toBeNull();
  });

  it('JSON mode Apply translates the document onto params and resolves', async () => {
    const spy = mockRoutes({
      translate: { params: { n_cells: 7 }, unmatched: [] },
      resolve: { state: { ok: true } },
    });
    const applied = vi.fn();
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} onApplied={applied} />);
    fireEvent.click(screen.getByRole('tab', { name: /JSON/ }));
    const box = screen.getByPlaceholderText(/matched onto this composite/i);
    fireEvent.change(box, { target: { value: '{"n_cells":7}' } });
    fireEvent.click(screen.getByText('Apply'));

    await waitFor(() => expect(applied).toHaveBeenCalled());
    // Translate was POSTed, resolve was called with the translated override.
    expect(spy).toHaveBeenCalledWith(
      '/api/composite-config-translate',
      expect.objectContaining({ method: 'POST' }),
    );
    const [ov] = applied.mock.calls[0];
    expect((ov as Record<string, unknown>).n_cells).toBe(7);
  });

  it('invalid JSON shows a client-side error and calls no endpoint', async () => {
    const spy = mockRoutes({});
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} />);
    fireEvent.click(screen.getByRole('tab', { name: /JSON/ }));
    fireEvent.change(screen.getByPlaceholderText(/matched onto this composite/i),
      { target: { value: '{not valid json' } });
    fireEvent.click(screen.getByText('Apply'));
    await waitFor(() => expect(document.querySelector('.cfg-error')).toBeTruthy());
    expect(document.querySelector('.cfg-error')!.textContent).toMatch(/not valid json/i);
    expect(spy).not.toHaveBeenCalled();
  });

  it('readOnly disables the JSON textarea', () => {
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} readOnly />);
    fireEvent.click(screen.getByRole('tab', { name: /JSON/ }));
    const box = screen.getByPlaceholderText(/matched onto this composite/i) as HTMLTextAreaElement;
    expect(box.disabled).toBe(true);
  });
});

describe('ConfigPanel — tabs + collapsible inputs', () => {
  it('tabs switch between Configure and Inputs without scrolling', () => {
    render(<ConfigPanel {...BASE_PROPS} parameters={PARAMS} />);
    expect(document.getElementById('explore-cfg-n_cells')).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /Inputs/ }));
    expect(document.getElementById('explore-cfg-n_cells')).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: /Configure/ }));
    expect(document.getElementById('explore-cfg-n_cells')).toBeTruthy();
  });

  it('input-tree deep groups start collapsed; expand-all / collapse-all toggle them', () => {
    // agents.0.environment.exchange.{GLC,ACET} — deeper than the default open
    // depth, so the leaves start hidden (high-level shape shown first).
    const state = {
      agents: { '0': { environment: { exchange: { GLC: 1, ACET: 2 } } } },
    };
    render(<ConfigPanel {...BASE_PROPS} parameters={{}} state={state} />);
    expect(screen.queryByText('GLC')).toBeNull();
    fireEvent.click(screen.getByText(/Expand all/));
    expect(screen.getByText('GLC')).toBeTruthy();
    fireEvent.click(screen.getByText(/Collapse all/));
    expect(screen.queryByText('GLC')).toBeNull();
  });
});

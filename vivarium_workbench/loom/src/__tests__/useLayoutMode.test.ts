import { describe, it, expect, beforeEach } from 'vitest';
import { loadLayout, saveLayout } from '../layoutStore';

// jsdom's localStorage here is partial (no clear()) — same gap viewStore.test.ts
// works around; install a Map-backed one so beforeEach can reset between tests.
function makeStorage(): Storage {
  const m = new Map<string, string>();
  return {
    getItem: (k) => (m.has(k) ? (m.get(k) as string) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
    clear: () => { m.clear(); },
    key: (i) => [...m.keys()][i] ?? null,
    get length() { return m.size; },
  } as Storage;
}

describe('mode-scoped layout persistence', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { value: makeStorage(), configurable: true });
    localStorage.clear();
  });

  it('keeps positions for different modes apart', () => {
    saveLayout('c1', { a: { x: 1, y: 1 } }, 'hierarchy');
    saveLayout('c1', { a: { x: 99, y: 99 } }, 'process-column');
    expect(loadLayout('c1', 'hierarchy')).toEqual({ a: { x: 1, y: 1 } });
    expect(loadLayout('c1', 'process-column')).toEqual({ a: { x: 99, y: 99 } });
  });

  it('defaults to the hierarchy scope when no mode is given', () => {
    saveLayout('c1', { a: { x: 5, y: 5 } });
    expect(loadLayout('c1', 'hierarchy')).toEqual({ a: { x: 5, y: 5 } });
  });

  it('keeps hierarchy on the un-suffixed key within the v2 namespace', () => {
    // The v2 namespace was bumped when the auto-layout algorithm changed to the
    // cluster-grid, so stale ELK positions saved under the old key don't override
    // the fresh layout. Within v2, hierarchy still uses the un-suffixed form.
    window.localStorage.setItem('bigraph-loom:layout:v2:c1', JSON.stringify({ a: { x: 7, y: 8 } }));
    expect(loadLayout('c1', 'hierarchy')).toEqual({ a: { x: 7, y: 8 } });
    expect(loadLayout('c1')).toEqual({ a: { x: 7, y: 8 } });
  });
});

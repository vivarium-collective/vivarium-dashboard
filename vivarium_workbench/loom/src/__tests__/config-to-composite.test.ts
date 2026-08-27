import { describe, it, expect, vi } from 'vitest';
import { configToComposite } from '../api';

describe('configToComposite', () => {
  it('posts the config to /api/config-to-composite and returns the document', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ state: { p: { _type: 'process' } }, schema: {} }) }));
    vi.stubGlobal('fetch', fetchMock);
    const out = await configToComposite({ add_processes: ['p'] });
    expect(fetchMock).toHaveBeenCalledWith('/api/config-to-composite', expect.objectContaining({ method: 'POST' }));
    expect((out.state as any).p._type).toBe('process');
  });
});

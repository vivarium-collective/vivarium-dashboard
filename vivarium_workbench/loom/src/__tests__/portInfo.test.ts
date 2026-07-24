import { describe, it, expect } from 'vitest';
import { portInfo } from '../portInfo';

describe('portInfo', () => {
  it('reports reads for inputs, writes for outputs', () => {
    expect(portInfo('a', false, {}).direction).toBe('reads');
    expect(portInfo('b', true, {}).direction).toBe('writes');
  });

  it('abbreviates a structured type but keeps the full form', () => {
    const info = portInfo('a', false, {
      typeSchema: { a: 'tree[float|integer|string]' },
    });
    expect(info.type).toBe('tree[3 fields]');
    expect(info.fullType).toBe('tree[float|integer|string]');
  });

  it('keeps a single-field container type literal', () => {
    const info = portInfo('a', false, { typeSchema: { a: 'map[float]' } });
    expect(info.type).toBe('map[float]');
    expect(info.fullType).toBe('map[float]');
  });

  it('prefers the resolved absolute target over the raw joined one', () => {
    const info = portInfo('a', false, {
      portsSchema: { a: 'unique.RNA' },
      portsTarget: { a: 'cell.molecules.unique.RNA' },
    });
    expect(info.connectsTo).toBe('cell.molecules.unique.RNA');
    expect(info.rawTarget).toBe('unique.RNA');
  });

  it('falls back to the raw target when no resolved path is present', () => {
    const info = portInfo('a', false, { portsSchema: { a: 'unique.RNA' } });
    expect(info.connectsTo).toBe('unique.RNA');
  });

  it('renders the composite root (resolved "") as <root>', () => {
    const info = portInfo('a', true, {
      portsSchema: { a: '' },
      portsTarget: { a: '' },
    });
    expect(info.connectsTo).toBe('<root>');
  });

  it('is empty-safe for an unwired, untyped port', () => {
    const info = portInfo('a', false, {});
    expect(info.type).toBe('');
    expect(info.fullType).toBe('');
    expect(info.connectsTo).toBe('');
    expect(info.rawTarget).toBe('');
  });

  it('ignores a non-string type schema entry', () => {
    const info = portInfo('a', false, { typeSchema: { a: { nested: true } as unknown } });
    expect(info.type).toBe('');
    expect(info.fullType).toBe('');
  });
});

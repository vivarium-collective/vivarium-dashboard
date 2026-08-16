import { describe, it, expect } from 'vitest';
import { topLevelStorePaths, defaultHiddenIds, stateToReactFlow } from '../convert';

describe('topLevelStorePaths', () => {
  it('returns top-level store keys, skipping process and step nodes', () => {
    const state = {
      biomodel_id: 'BIOMD0000000001',
      results: { copasi: {}, tellurium: {} },
      comparison: {},
      load: { _type: 'step', address: 'local:LoadBiomodelStep' },
      sim: { _type: 'process', address: 'local:Sim' },
    };
    expect(topLevelStorePaths(state)).toEqual([
      'biomodel_id', 'results', 'comparison',
    ]);
  });

  it('unwraps a {state: ...} envelope, like stateToReactFlow', () => {
    const doc = { state: { level: 1, proc: { _type: 'process' } } };
    expect(topLevelStorePaths(doc)).toEqual(['level']);
  });

  it('returns [] for empty or missing state', () => {
    expect(topLevelStorePaths({})).toEqual([]);
    expect(topLevelStorePaths(null)).toEqual([]);
  });
});

describe('defaultHiddenIds', () => {
  it('hides the injected emitter (and emitter_<i>) processes by default', () => {
    const state = {
      sim: { _type: 'process', address: 'local:Sim' },
      emitter: { _type: 'step', address: 'local:Emitter' },
      emitter_1: { _type: 'step', address: 'local:Emitter' },
      bulk: { count: 0 },
    };
    const hidden = defaultHiddenIds(state);
    expect(hidden.has('emitter')).toBe(true);
    expect(hidden.has('emitter_1')).toBe(true);
    expect(hidden.has('sim')).toBe(false);   // biology stays visible
  });
});


describe('stateToReactFlow — tree[node] topology', () => {
  it('recurses into a tree[node] store instead of rendering it as one leaf', () => {
    const state = {
      colony: { _type: 'tree[node]',
        cell: { _control: 'cell',
          contents: { chromosome: { _control: 'chromosome', contents: { dna: 1.0 } } } } },
    };
    const { nodes } = stateToReactFlow(state);
    const ids = nodes.map((n) => n.id);
    // the place-graph children render as their own nodes (not collapsed into `colony`)
    expect(ids).toContain('colony');
    expect(ids).toContain('colony.cell');
    expect(ids.some((i) => i.includes('chromosome'))).toBe(true);
  });

  it('reflects a divided topology as two daughter-cell nodes', () => {
    const divided = {
      colony: { _type: 'tree[node]',
        cell_0: { _control: 'cell', chromosome_0: { _control: 'chromosome' } },
        cell_1: { _control: 'cell', chromosome_1: { _control: 'chromosome' } } },
    };
    const ids = stateToReactFlow(divided).nodes.map((n) => n.id);
    expect(ids).toContain('colony.cell_0');
    expect(ids).toContain('colony.cell_1');
  });

  it('still renders an ordinary map[float] store as a single typed leaf', () => {
    const { nodes } = stateToReactFlow({ field: { _type: 'map[float]', a: 0.1, b: 0.2 } });
    const field = nodes.find((n) => n.id === 'field');
    expect(field?.data.nodeType).toBe('store');
    // not expanded into child nodes
    expect(nodes.map((n) => n.id)).not.toContain('field.a');
  });
});

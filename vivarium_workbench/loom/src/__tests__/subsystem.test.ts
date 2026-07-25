import { describe, it, expect } from 'vitest';
import type { Node } from '@xyflow/react';
import { subsystemOf, subsystemClusters, locationClusters } from '../layouts/subsystem';

function proc(id: string, label: string, path?: string[]): Node {
  return {
    id, type: 'process', position: { x: 0, y: 0 },
    data: { label, ...(path ? { path } : {}) },
  } as unknown as Node;
}

describe('subsystemOf', () => {
  it('maps v2ecoli name families to biological subsystems', () => {
    expect(subsystemOf('ecoli-transcript-initiation')).toBe('Transcription');
    expect(subsystemOf('ecoli-polypeptide-elongation')).toBe('Translation');
    expect(subsystemOf('ecoli-chromosome-replication')).toBe('Replication & division');
    expect(subsystemOf('division')).toBe('Replication & division');
    expect(subsystemOf('ecoli-rna-degradation_evolver')).toBe('RNA processing & decay');
    expect(subsystemOf('ecoli-metabolism')).toBe('Metabolism');
    expect(subsystemOf('ecoli-tf-binding')).toBe('Gene regulation');
    expect(subsystemOf('ppgpp-initiation')).toBe('Stringent response');
    expect(subsystemOf('counts_deriver')).toBe('Observation');
  });

  it('specific rules beat generic (rna-degradation is decay, not transcription)', () => {
    // "rna-degradation" must not fall through to a bare rna/transcript rule.
    expect(subsystemOf('ecoli-rna-maturation')).toBe('RNA processing & decay');
  });

  it('falls back to Other for an unrecognised name', () => {
    expect(subsystemOf('some-mystery-step')).toBe('Other');
  });
});

describe('subsystemClusters', () => {
  it('groups processes by subsystem, ignores store nodes, sorts members', () => {
    const nodes = [
      proc('p2', 'ecoli-transcript-elongation'),
      proc('p1', 'ecoli-transcript-initiation'),
      proc('m', 'ecoli-metabolism'),
      { id: 's', type: 'store', position: { x: 0, y: 0 }, data: { label: 'bulk' } } as unknown as Node,
    ];
    const clusters = subsystemClusters(nodes);
    const tx = clusters.find((c) => c.label === 'Transcription');
    expect(tx?.processIds).toEqual(['p1', 'p2']);            // sorted
    expect(clusters.some((c) => c.processIds.includes('s'))).toBe(false);  // no store
    // Transcription sorts before Metabolism (declaration order).
    expect(clusters.map((c) => c.label)).toEqual(['Transcription', 'Metabolism']);
  });
});

describe('locationClusters', () => {
  it('groups by containing composite path, biggest first', () => {
    const nodes = [
      proc('a', 'proc-a', ['agents', '0', 'proc-a']),
      proc('b', 'proc-b', ['agents', '0', 'proc-b']),
      proc('c', 'proc-c', ['proc-c']),          // top-level → <root>
    ];
    const clusters = locationClusters(nodes);
    expect(clusters[0].label).toBe('agents.0');           // biggest first
    expect(clusters[0].processIds).toEqual(['a', 'b']);
    expect(clusters.find((c) => c.label === '<root>')?.processIds).toEqual(['c']);
  });
});

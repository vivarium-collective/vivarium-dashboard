// src/portInfo.ts — what one process port advertises: its TYPE and WHERE it wires.
//
// A pure function that folds a port's several data sources (the process's
// _inputs/_outputs type schema, the raw authored wire target, and the resolved
// absolute store path) into the small shape the port hover tooltip and the
// Inspector render. No React, no DOM — unit-tested in isolation.

import { abbreviateType } from './contract';

export interface PortInfo {
  port: string;
  /** A port on `_inputs` READS its store; one on `_outputs` WRITES it. */
  direction: 'reads' | 'writes';
  /** Abbreviated type (structured shapes collapse to `Base[N fields]`); '' when
   *  the process declares no type for this port. */
  type: string;
  /** Full, unabbreviated type string; '' when none. Goes in a title / expanded row. */
  fullType: string;
  /** The store the port connects to, for display: the RESOLVED absolute dotted
   *  path when known (the composite root shown as `<root>`), else the raw
   *  authored target. '' when the port is unwired. */
  connectsTo: string;
  /** The raw authored wire target, joined verbatim (lossy — never re-split). */
  rawTarget: string;
}

export interface PortSchemas {
  /** port -> type string (from the process spec's _inputs/_outputs). */
  typeSchema?: Record<string, unknown>;
  /** port -> raw authored wire target, joined with '.'. */
  portsSchema?: Record<string, string>;
  /** port -> resolved absolute dotted store path ('' = composite root). */
  portsTarget?: Record<string, string>;
}

/** A port's declared type as a string. Handles the two authored forms:
 *  - bare type string (how `outputs()` writes it): `"rna"`
 *  - schema dict (how `inputs()` writes it): `{_type: "rna", _default: []}`
 *  A compound port group with no top-level `_type` (e.g. ppgpp_state's
 *  sub-fields) has no single type → ''. */
function portType(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v && typeof v === 'object') {
    const t = (v as { _type?: unknown })._type;
    if (typeof t === 'string') return t;
  }
  return '';
}

/** Fold a single port's type + wiring into its display shape. */
export function portInfo(port: string, isOutput: boolean, s: PortSchemas): PortInfo {
  const rawType = s.typeSchema ? portType(s.typeSchema[port]) : '';
  const rawTarget = s.portsSchema?.[port] ?? '';
  const resolved = s.portsTarget?.[port];
  // The resolved absolute path is unambiguous, so prefer it; '' is the valid
  // composite-root path (falsy but meaningful), rendered as <root>. Fall back to
  // the raw authored target when no resolution is available.
  const connectsTo = resolved != null
    ? (resolved === '' ? '<root>' : resolved)
    : rawTarget;
  return {
    port,
    direction: isOutput ? 'writes' : 'reads',
    type: abbreviateType(rawType),
    fullType: rawType,
    connectsTo,
    rawTarget,
  };
}

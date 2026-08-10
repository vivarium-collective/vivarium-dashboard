import { memo, useEffect, useState } from "react";
import { Handle, Position, NodeResizer, useReactFlow, useNodeId, type NodeProps } from "@xyflow/react";
import type { ProcessNodeData } from "../types";
import { deriveContract, contractCompleteness } from "../contract";
import { portInfo } from "../portInfo";
import { KatexBlock } from "../Katex";
import InnerCompositePreview from "./InnerCompositePreview";
import { configParams } from "../configView";

function _classifyStep(address: string | undefined, label: string | undefined): 'process' | 'emitter' | 'visualization' {
  const addr = address || '';
  const lbl = label || '';
  // Emitter convention: process-bigraph emitters end with 'Emitter' OR labeled emitter_*
  if (/Emitter\b/.test(addr) || /^(sqlite_)?emitter\b|^user_emitter\b/.test(lbl)) {
    return 'emitter';
  }
  // Visualization-class heuristic — by-class-name OR by viz_* convention on the step label.
  // Covers TestSuiteTimeSeries, FieldSnapshotsGrid, FieldAnimationGif, FieldHeatmap, DemoTimeSeriesPlot,
  // BondNetworkPlots, MembranePlots, Distribution, PhaseSpace, ParamVsObservable, TimeSeriesPlot, etc.
  if (/(Plot|Heatmap|Animation|Snapshots|Distribution|Viz|TimeSeries|Series|Chart|Trajectory|Histogram|PhaseSpace|ParamVs)/i.test(addr)
      || /^viz[_-]/i.test(lbl)) {
    return 'visualization';
  }
  return 'process';
}

/** One-line "what is this section" hints, shown on hover of each middle box. */
const SECTION_HINT = {
  config:   'Configuration — build-time parameters that set how this process behaves. Click for values & types.',
  meta:     'Process type and how many input / output ports it has.',
  contract: 'Contract — what this process reads, computes, and writes. Click for the full description.',
  math:     'Governing equations — how the outputs are computed from the inputs.',
  symbols:  'Symbol legend — what each variable in the equations means.',
} as const;

/**
 * Legacy card body: centered label + type with flanking port labels. Used in
 * modes that do NOT drive semantic zoom (hierarchy). Preserved verbatim so
 * hierarchy renders exactly as before this task — semantic zoom is opt-in via a
 * stamped `_tier`, which only process-column mode sets.
 */
function LegacyBody({ data, stepKind }: {
  data: ProcessNodeData;
  stepKind: 'process' | 'emitter' | 'visualization';
}) {
  const inputPorts = data.inputPorts ?? [];
  const outputPorts = data.outputPorts ?? [];
  const portSchema = data.inputPortsSchema ?? {};
  const outSchema = data.outputPortsSchema ?? {};
  return (
    <div className={`process-node process-node-${stepKind}`}>
      {inputPorts.map((port, i) => {
        const typeStr = portSchema[port] ? String(portSchema[port]) : undefined;
        const top = `${((i + 1) / (inputPorts.length + 1)) * 100}%`;
        return (
          <div key={`in-${port}`}>
            <Handle
              type="target"
              position={Position.Left}
              id={port}
              className="port-handle port-handle-input"
              style={{ top }}
            />
            <div className="port-label port-label-left" style={{ top }}>
              <span className="port-label-name">{port}</span>
              {typeStr && (
                <span className="port-label-tooltip">{typeStr}</span>
              )}
            </div>
          </div>
        );
      })}

      <div className="process-body">
        <div className="process-label">
          {data.label}
          {(data as any).isDraft && (
            <span className="process-node-draft" title="Draft process — typed ports + contract, but NO update dynamics yet">
              DRAFT
            </span>
          )}
          {data.isCompositeProcess && (
            <span
              className="process-node-drill"
              title="Composite Process — double-click to open its inner composite"
            >
              {' '}⤢
            </span>
          )}
        </div>
        <div className="process-type">{data.processType}</div>
      </div>

      {outputPorts.map((port, i) => {
        const typeStr = outSchema[port] ? String(outSchema[port]) : undefined;
        const top = `${((i + 1) / (outputPorts.length + 1)) * 100}%`;
        return (
          <div key={`out-${port}`}>
            <Handle
              type="source"
              position={Position.Right}
              id={port}
              className="port-handle port-handle-output"
              style={{ top }}
            />
            <div className="port-label port-label-right" style={{ top }}>
              <span className="port-label-name">{port}</span>
              {typeStr && (
                <span className="port-label-tooltip">{typeStr}</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ProcessNode({ data }: NodeProps & { data: ProcessNodeData }) {
  const inputPorts = data.inputPorts ?? [];
  const outputPorts = data.outputPorts ?? [];
  const stepKind = _classifyStep((data as any).address, data.label);

  // Semantic zoom is opt-in: only process-column mode stamps `_tier` (or
  // `_pinnedOpen`). Absent both, render the legacy fixed card so hierarchy mode
  // is untouched.
  if ((data as any)._tier == null && !(data as any)._pinnedOpen) {
    return <LegacyBody data={data} stepKind={stepKind} />;
  }

  // Semantic zoom: the stamped tier decides WHICH rows exist. Font size is
  // constant across tiers (see App.css) — legibility at low zoom comes from
  // dropping content, never from shrinking text. A pinned-open card always
  // shows full detail regardless of the current zoom tier.
  const tier = ((data as any)._tier ?? 'ports') as
    'glyph' | 'ports' | 'types' | 'config' | 'contract' | 'full';
  const t = (data as any)._pinnedOpen ? 'full' : tier;

  const show = {
    ports:    t !== 'glyph',
    types:    t === 'types' || t === 'config' || t === 'contract' || t === 'full',
    // The config band moved to its own tier (between Port types and Contracts):
    // it appears from `config` up, NOT at the `types` tier.
    config:   t === 'config' || t === 'contract' || t === 'full',
    contract: t === 'contract' || t === 'full',
    full:     t === 'full',
  };
  // Per-feature Detail overrides (the Detail menu) layer on top of the tier: each
  // feature is 'auto' (keep the tier value) or forced. Never applied to a pinned-
  // open card (that always shows everything).
  const ov = (data as any)._detailOverrides as
    { ports?: string; config?: string; contract?: string } | undefined;
  if (ov && !(data as any)._pinnedOpen) {
    if (ov.ports === 'none')  { show.ports = false; show.types = false; }
    else if (ov.ports === 'plain') { show.ports = true;  show.types = false; }
    else if (ov.ports === 'types') { show.ports = true;  show.types = true; }
    if (ov.config === 'on')  show.config = true;  else if (ov.config === 'off')  show.config = false;
    // 'full' = show the contract AND its full extended description (what you get
    // by clicking the process open), not just the summary.
    if (ov.contract === 'on') show.contract = true;
    else if (ov.contract === 'off') show.contract = false;
    else if (ov.contract === 'full') { show.contract = true; show.full = true; }
  }

  const contract = show.contract ? deriveContract(data) : null;
  const completeness = show.full ? contractCompleteness(contract, data) : null;
  const inTypes = ((data as any).inputSchema ?? {}) as Record<string, unknown>;
  const outTypes = ((data as any).outputSchema ?? {}) as Record<string, unknown>;
  // Config comes from the declared schema (types + defaults), overlaid with any
  // set values — NOT just `data.config`, which is usually {} (defaults in use).
  const cfg = configParams(
    (data as { configSchema?: Record<string, unknown> }).configSchema,
    data.config,
  );
  // The config band shows real configuration KEYS only — drop the metadata keys
  // (summary / contract / status) that ride along in a draft process's config
  // dict; the summary belongs to the meta/contract, not the config.
  const CONFIG_META = new Set(["summary", "contract", "status", "description", "math", "symbols", "ports"]);
  const realCfg = cfg.filter((c) => !CONFIG_META.has(c.name));

  const topFor = (i: number, n: number) => `${((i + 1) / (n + 1)) * 100}%`;

  // Connection dots sit ON the card border (inputs left, outputs right) at each
  // port's vertical fraction — that's where wires attach, at every tier.
  const borderHandle = (
    port: string, isOut: boolean, i: number, n: number, types: Record<string, unknown>,
  ) => (
    <Handle
      key={`h-${isOut ? 'o' : 'i'}-${port}`}
      type={isOut ? 'source' : 'target'}
      position={isOut ? Position.Right : Position.Left}
      id={port}
      className={`port-handle ${isOut ? 'port-handle-output' : 'port-handle-input'}`}
      title={handleTitle(port, isOut, types)}
      style={{ top: topFor(i, n) }}
    />
  );

  // Port names live INSIDE the card in a left column (inputs) and a right column
  // (outputs), each aligned to its dot. The center content is margined clear of
  // these columns, so the card reads inputs → contract → outputs spatially.
  const insideLabel = (
    port: string, types: Record<string, unknown>, isOut: boolean, i: number, n: number,
  ) => {
    const info = portInfo(port, isOut, {
      typeSchema: types,
      portsSchema: isOut ? (data.outputPortsSchema ?? undefined) : (data.inputPortsSchema ?? undefined),
      portsTarget: isOut ? (data.outputPortsTarget ?? undefined) : (data.inputPortsTarget ?? undefined),
    });
    const key = `${isOut ? 'o' : 'i'}-${port}`;
    const open = openPort === key;
    const semantic = isOut ? contract?.outputs?.[port] : contract?.inputs?.[port];
    return (
      <div
        key={`${isOut ? 'o' : 'i'}lbl-${port}`}
        className={`port-in-label ${isOut ? 'is-out' : 'is-in'}${open ? ' is-open' : ''}`}
        style={{ top: topFor(i, n) }}
        title={handleTitle(port, isOut, types)}
        onClick={(e) => { e.stopPropagation(); setOpenPort(open ? null : key); }}
      >
        <span className="port-in-name">{port}</span>
        {show.types && info.type && (
          <span className="port-in-type" title={info.fullType}>{info.type}</span>
        )}
        {open && (
          <div className={`port-popover ${isOut ? 'is-out' : 'is-in'}`} onClick={(e) => e.stopPropagation()}>
            <div className="port-popover-head">
              <span className="port-popover-name">{port}</span>
              <span className={`port-popover-dir ${info.direction}`}>{info.direction}</span>
            </div>
            <div className="port-popover-row">
              <span className="port-popover-key">connects to</span>
              <span className="port-popover-val mono">{info.connectsTo || '(unwired)'}</span>
            </div>
            {info.fullType && (
              <div className="port-popover-row">
                <span className="port-popover-key">type</span>
                <span className="port-popover-val mono">{info.fullType}</span>
              </div>
            )}
            {semantic && <div className="port-popover-sem">{semantic}</div>}
          </div>
        )}
      </div>
    );
  };

  // A terse native tooltip for the raw handle (present at every tier, incl.
  // glyph where no port rows are drawn) so hovering the connector itself still
  // reveals direction + target.
  const handleTitle = (port: string, isOut: boolean, types: Record<string, unknown>) => {
    const info = portInfo(port, isOut, {
      typeSchema: types,
      portsSchema: isOut ? (data.outputPortsSchema ?? undefined) : (data.inputPortsSchema ?? undefined),
      portsTarget: isOut ? (data.outputPortsTarget ?? undefined) : (data.inputPortsTarget ?? undefined),
    });
    const parts = [`${port} · ${info.direction}`];
    if (info.connectsTo) parts.push(`→ ${info.connectsTo}`);
    if (info.type) parts.push(`(${info.type})`);
    return parts.join(' ');
  };

  const locked = (data as any)._locked === true;

  // Manual resize: drag a corner to pull the card bigger. In-session inline
  // override of the tier size. The corner handles are HIDDEN by default and
  // revealed only on card hover (CSS), so they don't clutter every card — the
  // functionality is there, just not always visible.
  // Hand-set size persists on data._size (saved with the layout/default view);
  // local `dims` gives smooth drag feedback, seeded from + synced to it.
  const _rf = useReactFlow();
  const _nodeId = useNodeId();
  const savedSize = (data as any)._size as { width: number; height: number } | undefined;
  const [dims, setDims] = useState<{ width: number; height: number } | null>(savedSize ?? null);
  useEffect(() => {
    if (savedSize) setDims(savedSize);
  }, [savedSize?.width, savedSize?.height]);
  const commitSize = (w: number, h: number) => {
    if (!_nodeId) return;
    // Route through App's commit so the size lands in the persisted node state
    // (a bare _rf.setNodes writes React Flow's store but not useNodesState, so
    // the size silently reset on the next reload).
    const commit = (data as any)._commitSize as
      | ((id: string, s: { width: number; height: number }) => void) | undefined;
    if (commit) commit(_nodeId, { width: w, height: h });
    else _rf.setNodes((ns: any[]) => ns.map((n) =>
      n.id === _nodeId ? { ...n, data: { ...n.data, _size: { width: w, height: h } } } : n));
  };
  // Which port's info popover is open (click a port name). Keyed 'i-'/'o-'+port.
  const [openPort, setOpenPort] = useState<string | null>(null);
  // Which middle section's detail is expanded (click a center box). 'config'
  // opens a values+types popover; 'contract' reveals the full description.
  const [openSection, setOpenSection] = useState<'config' | 'contract' | null>(null);
  const toggleSection = (s: 'config' | 'contract') =>
    setOpenSection((cur) => (cur === s ? null : s));

  // The card's minimum height must fit BOTH its text (CSS min-content) AND its
  // evenly-spaced port rows. Ports are absolutely positioned (out of flow), so
  // min-content can't see them — feed the room they need as a CSS var that the
  // min-height max()es against, so squeezing never overlaps the ports.
  const maxPorts = show.ports ? Math.max(inputPorts.length, outputPorts.length) : 0;
  const portsMinH = maxPorts > 0 ? (maxPorts + 1) * 46 : 0;

  return (
    <div
      className={`process-node process-node-${stepKind} process-node-${t}${locked ? ' is-locked' : ''}${!show.ports ? ' process-node-noports' : ''}`}
      style={{
        ...(dims ? { width: dims.width, height: dims.height, overflow: 'visible' } : {}),
        ['--ports-min-h' as string]: `${portsMinH}px`,
      } as React.CSSProperties}
    >
      <NodeResizer
        isVisible={show.ports}
        minWidth={160}
        minHeight={56}
        onResize={(_e, p) => setDims({ width: p.width, height: p.height })}
        onResizeEnd={(_e, p) => commitSize(p.width, p.height)}
        handleClassName="loom-resize-handle"
        lineClassName="loom-resize-line"
      />
      {/* Connection dots on the border (all tiers, so focused wiring attaches). */}
      {inputPorts.map((p, i) => borderHandle(p, false, i, inputPorts.length, inTypes))}
      {outputPorts.map((p, i) => borderHandle(p, true, i, outputPorts.length, outTypes))}

      {/* Port-name columns INSIDE the card: inputs left, outputs right. */}
      {show.ports && inputPorts.map((p, i) => insideLabel(p, inTypes, false, i, inputPorts.length))}
      {show.ports && outputPorts.map((p, i) => insideLabel(p, outTypes, true, i, outputPorts.length))}

      {/* Center channel — margined clear of the port columns. Reads top-down:
          config (from above) → title → the contract (what inputs become). The
          left/right port columns supply the inputs→outputs framing spatially,
          so no abstract ƒ(inputs; config)→outputs line is needed. */}
      <div className="process-node-center">
        {show.config && realCfg.length > 0 && (
          <div className="process-node-config-band" title={SECTION_HINT.config}>
            <span className="config-band-caret">config</span>
            {realCfg.slice(0, 10).map((c) => (
              <span key={c.name} className="config-chip" title={`${c.name}: ${c.type || '—'}${c.value ? ' = ' + c.value : ''}`}>
                <span className="config-key">{c.name}</span>
                {/* Types ride the port-detail level: shown once ports show types. */}
                {show.types && c.type && <span className="config-type">{c.type}</span>}
              </span>
            ))}
            {realCfg.length > 10 && (
              <span className="config-more">+{realCfg.length - 10} more…</span>
            )}
          </div>
        )}

        <div className="process-node-title">
          {locked && <span className="process-node-lock" title="Locked — click empty canvas to unlock">🔒</span>}
          {data.label}
          {/* Collapsed array of identical processes → how many this stands for. */}
          {(data as any)._collapsedCount > 1 && (
            <span className="process-node-count" title={`${(data as any)._collapsedCount} identical processes collapsed into this one`}>
              ×{(data as any)._collapsedCount}
            </span>
          )}
          {/* No separate DRAFT badge — the meta line below reads "draft process"
              instead of "process" (more discrete, shown from the ports tier up). */}
          {data.isCompositeProcess && (
            <span
              className="process-node-drill"
              title="Composite Process — double-click to open its inner composite"
            >
              ⤢
            </span>
          )}
        </div>
        {show.ports && (
          <div className="process-node-meta" title={SECTION_HINT.meta}>
            {/* "draft process" / "process" — the in/out counts are omitted: the
                port columns already make the arity obvious. */}
            {(data as any).isDraft ? `draft ${data.processType}` : data.processType}
            {data.interval != null && <span> · every {data.interval}</span>}
          </div>
        )}

        {/* Composite Process: render a live mini-map of its INNER composite in
            place of the contract, at the contract+ tier. Auto-loads at `full`
            tier (the focused/most-zoomed card); at `contract` tier it shows the
            ⤢ viz icon to render on demand — so zoom doesn't trigger a ParCa
            build on every card at once. Double-click still opens the full view. */}
        {show.contract && data.isCompositeProcess && (data as any)._rootId && (
          <InnerCompositePreview
            rootId={(data as any)._rootId}
            hops={[...(((data as any)._hops as string[][]) ?? []), data.path]}
            auto
          />
        )}

        {/* The contract: a justified recital of what the process does, over its
            governing equations. Only shown when actually documented. Click to
            reveal the full description below (when there is one to reveal).
            Composite Processes show their inner mini-map above instead. */}
        {show.contract && !data.isCompositeProcess && contract?.summary && (
          <div
            className={`process-contract section-box${openSection === 'contract' ? ' is-open' : ''}`}
            title={SECTION_HINT.contract}
            onClick={(e) => {
              if (!contract.description || contract.description === contract.summary) return;
              e.stopPropagation(); toggleSection('contract');
            }}
          >
            <p className="contract-recital">{contract.summary}</p>
          </div>
        )}

        {show.contract && contract && contract.math.length > 0 && (
          <div className="process-node-math" title={SECTION_HINT.math}>
            {contract.math.map((m, i) => <KatexBlock key={i} tex={m} />)}
          </div>
        )}

        {show.full && contract && Object.keys(contract.symbols).length > 0 && (
          <div className="process-node-symbols" title={SECTION_HINT.symbols}>
            {Object.entries(contract.symbols).map(([s, meaning]) => (
              <div key={s}><em>{s}</em> — {meaning}</div>
            ))}
          </div>
        )}

        {/* Full description: shown at the `full` tier, OR on demand when the
            contract box is clicked at the `contract` tier. */}
        {(show.full || openSection === 'contract') && contract?.description
          && contract.description !== contract.summary && (
          <div className="process-node-description">{contract.description}</div>
        )}

        {show.types && (data as any).address && (
          <div className="process-node-address">{(data as any).address}</div>
        )}

        {show.full && completeness && completeness.total > 0 && (
          <div className="process-node-completeness">
            {completeness.documented}/{completeness.total} ports documented
            {completeness.unknownPorts.length > 0 && (
              <span className="is-warn"> · unknown: {completeness.unknownPorts.join(', ')}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(ProcessNode);

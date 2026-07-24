import { memo, useState } from "react";
import { Handle, Position, NodeResizer, type NodeProps } from "@xyflow/react";
import type { ProcessNodeData } from "../types";
import { deriveContract, contractCompleteness } from "../contract";
import { portInfo } from "../portInfo";

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
        <div className="process-label">{data.label}</div>
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
    'glyph' | 'ports' | 'types' | 'contract' | 'full';
  const t = (data as any)._pinnedOpen ? 'full' : tier;

  const show = {
    ports:    t !== 'glyph',
    types:    t === 'types' || t === 'contract' || t === 'full',
    contract: t === 'contract' || t === 'full',
    full:     t === 'full',
  };

  const contract = show.contract ? deriveContract(data) : null;
  const completeness = show.full ? contractCompleteness(contract, data) : null;
  const inTypes = ((data as any).inputSchema ?? {}) as Record<string, unknown>;
  const outTypes = ((data as any).outputSchema ?? {}) as Record<string, unknown>;
  const configEntries = Object.entries(data.config ?? {});

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
    return (
      <div
        key={`${isOut ? 'o' : 'i'}lbl-${port}`}
        className={`port-in-label ${isOut ? 'is-out' : 'is-in'}`}
        style={{ top: topFor(i, n) }}
        title={handleTitle(port, isOut, types)}
      >
        <span className="port-in-name">{port}</span>
        {show.types && info.type && (
          <span className="port-in-type" title={info.fullType}>{info.type}</span>
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

  // Manual resize: drag a corner to pull the card bigger (handy when the center
  // contract is dense). Local, inline override of the default tier width/height;
  // in-session only. Handles show once ports are visible (not at the glyph tier).
  const [dims, setDims] = useState<{ width: number; height: number } | null>(null);

  return (
    <div
      className={`process-node process-node-${stepKind} process-node-${t}${locked ? ' is-locked' : ''}`}
      style={dims ? { width: dims.width, height: dims.height, overflow: 'auto' } : undefined}
    >
      <NodeResizer
        isVisible={show.ports}
        minWidth={360}
        minHeight={200}
        onResize={(_e, p) => setDims({ width: p.width, height: p.height })}
        handleStyle={{ width: 9, height: 9, borderRadius: 2, background: '#fff', borderColor: '#6366f1' }}
        lineStyle={{ borderColor: 'transparent' }}
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
        {show.types && configEntries.length > 0 && (
          <div className="process-node-config-band" title="config parameters">
            <span className="config-band-caret">▼ config</span>
            {configEntries.map(([k, v]) => (
              <span key={k} className="config-chip">
                <span className="config-key">{k}</span>
                {show.contract && <span className="config-val">{String(v).slice(0, 24)}</span>}
              </span>
            ))}
          </div>
        )}

        <div className="process-node-title">
          {locked && <span className="process-node-lock" title="Locked — click empty canvas to unlock">🔒</span>}
          {data.label}
        </div>

        {show.ports && (
          <div className="process-node-meta">
            {data.processType} · {inputPorts.length} in / {outputPorts.length} out
            {data.interval != null && <span> · every {data.interval}</span>}
          </div>
        )}

        {/* The contract: a justified recital of what the process does, over its
            governing equations. Only shown when actually documented. */}
        {show.contract && contract?.summary && (
          <div className="process-contract">
            <p className="contract-recital">{contract.summary}</p>
          </div>
        )}

        {show.contract && contract && contract.math.length > 0 && (
          <div className="process-node-math">
            {contract.math.map((m, i) => <div key={i}>{m}</div>)}
          </div>
        )}

        {show.full && contract && Object.keys(contract.symbols).length > 0 && (
          <div className="process-node-symbols">
            {Object.entries(contract.symbols).map(([s, meaning]) => (
              <div key={s}><em>{s}</em> — {meaning}</div>
            ))}
          </div>
        )}

        {show.full && contract?.description && (
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

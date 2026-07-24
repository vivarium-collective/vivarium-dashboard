import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
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

  // Port labels live OUTSIDE the card border — inputs to the left, outputs to
  // the right — aligned to their vertical position. The connection dot (the RF
  // Handle) sits at the OUTER END of the name, so wires leave from the tip of
  // the label instead of crossing it. The name shows at `ports`; the abbreviated
  // type beneath at `types`+. Full per-port detail is revealed on click (1b).
  // Rendered at EVERY tier (the dot must exist at glyph for wires to attach);
  // only the text is tier-gated.
  const outsideLabel = (
    port: string, types: Record<string, unknown>, isOut: boolean, i: number, n: number,
  ) => {
    const info = portInfo(port, isOut, {
      typeSchema: types,
      portsSchema: isOut ? (data.outputPortsSchema ?? undefined) : (data.inputPortsSchema ?? undefined),
      portsTarget: isOut ? (data.outputPortsTarget ?? undefined) : (data.inputPortsTarget ?? undefined),
    });
    const dot = (
      <Handle
        type={isOut ? 'source' : 'target'}
        position={isOut ? Position.Right : Position.Left}
        id={port}
        className={`port-dot ${isOut ? 'is-out' : 'is-in'}`}
        title={handleTitle(port, isOut, types)}
      />
    );
    const text = show.ports ? (
      <span className="port-out-text">
        <span className="port-out-name">{port}</span>
        {show.types && info.type && (
          <span className="port-out-type" title={info.fullType}>{info.type}</span>
        )}
      </span>
    ) : null;
    return (
      <div
        key={`${isOut ? 'o' : 'i'}lbl-${port}`}
        className={`port-out-label ${isOut ? 'is-out' : 'is-in'}`}
        style={{ top: `${((i + 1) / (n + 1)) * 100}%` }}
      >
        {isOut ? <>{text}{dot}</> : <>{dot}{text}</>}
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

  return (
    <div className={`process-node process-node-${stepKind} process-node-${t}${locked ? ' is-locked' : ''}`}>
      {/* Port names OUTSIDE the card — inputs flow in from the left, outputs
          leave to the right — with the connection dot at the name's outer end so
          wires attach past the text, not through it. Rendered at every tier
          (the dot must exist at glyph so focused wiring can attach by port id). */}
      {inputPorts.map((p, i) => outsideLabel(p, inTypes, false, i, inputPorts.length))}
      {outputPorts.map((p, i) => outsideLabel(p, outTypes, true, i, outputPorts.length))}

      {/* Config enters from ABOVE the process — the knobs that parameterize the
          input→output translation. Keys at `types`, key=value at `contract`+. */}
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

      {/* The contract, presented as a formal document: a mathematical function
          signature ƒ(inputs; config) ⟶ outputs (inputs transformed to outputs,
          parameterized by config) over a justified recital (the summary). */}
      {show.contract && (
        <div className="process-contract">
          <div className="contract-signature">
            <span className="sig-fn">ƒ</span>
            <span className="sig-punct">(</span>
            <span className="sig-in">inputs</span>
            <span className="sig-sep">;</span>
            <span className="sig-config">config</span>
            <span className="sig-punct">)</span>
            <span className="sig-maps">⟶</span>
            <span className="sig-out">outputs</span>
          </div>
          {contract?.summary && <p className="contract-recital">{contract.summary}</p>}
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
  );
}

export default memo(ProcessNode);

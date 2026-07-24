// src/panels/InspectorPanel.tsx — selected-node detail.
//
// Extracted verbatim from the old right-sidebar "Inspector" tab so it can dock
// independently. Updates on canvas node click (App's handleNodeClick →
// setSelection). Stores show their raw schema; a process gets a COMPREHENSIVE
// detail view — every port with its type + wired store + contract meaning, plus
// config, math, symbols, assumptions and references — so a locked (clicked)
// process reads as a real reference panel, not just a couple of fields.

import type React from 'react';
import type { ExploreInspectMsg } from '../api';
import type { ProcessNodeData } from '../types';
import { deriveContract } from '../contract';
import { portInfo } from '../portInfo';

type Selection = Omit<ExploreInspectMsg, 'type'> | null;

export interface InspectorPanelProps {
  selection: Selection;
  /** True when the selected node is the locked (clicked) one — shows a lock chip. */
  locked?: boolean;
}

export function InspectorPanel(props: InspectorPanelProps) {
  const sel = props.selection;
  if (!sel) {
    return <p style={{ color: '#888', fontSize: 12 }}>Click a node to inspect.</p>;
  }

  return (
    <div>
      <h4 style={{
        margin: 0, fontSize: 14, textTransform: 'capitalize',
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        {props.locked && <span title="Locked — click empty canvas to unlock">🔒</span>}
        {sel.kind}
      </h4>
      <p style={{ fontFamily: 'monospace', fontSize: 12, margin: '4px 0' }}>
        {sel.path.length ? sel.path.join('.') : '<root>'}
      </p>

      {sel.kind === 'process' ? (
        <ProcessDetail details={sel.details as unknown as ProcessNodeData} />
      ) : (
        <StoreDetail details={sel.details} />
      )}
    </div>
  );
}

/** Store inspector: description (if any) then the raw schema. */
function StoreDetail(props: { details: Record<string, unknown> }) {
  const description = (props.details as { description?: unknown })?.description;
  const hasDescription = typeof description === 'string' && description.trim().length > 0;
  return (
    <>
      {hasDescription && (
        <InspectorSection title="Description">
          <Prose text={description as string} />
        </InspectorSection>
      )}
      <InspectorSection title="Details">
        <SchemaBlock value={props.details} />
      </InspectorSection>
    </>
  );
}

/** A labeled inspector section — collapsible (open by default) so long schemas
 * can be folded away. Content flows at full height into the panel's single
 * scrollbar; no inner scroll box. */
function InspectorSection(props: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="inspector-section" open={props.defaultOpen !== false} style={{ margin: '10px 0' }}>
      <summary style={{
        fontSize: 12, fontWeight: 600, color: '#374151', cursor: 'pointer',
        userSelect: 'none', display: 'flex', alignItems: 'center', gap: 5,
      }}>
        <span className="inspector-caret" style={{ fontSize: 9, color: '#9ca3af' }}>▶</span>
        {props.title}
      </summary>
      <div style={{ marginTop: 5 }}>{props.children}</div>
    </details>
  );
}

function Prose(props: { text: string }) {
  return (
    <pre style={{
      fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      background: '#f7f7f7', padding: 8, margin: 0, borderRadius: 4,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', color: '#1f2937',
      lineHeight: 1.5,
    }}>
      {props.text}
    </pre>
  );
}

/** A pretty-printed JSON block, or an em-dash when empty. Flows at full height —
 * long lines wrap (no inner scrollbar); the inspector panel scrolls as a whole. */
function SchemaBlock(props: { value: unknown }) {
  const v = props.value;
  const empty = v == null
    || (typeof v === 'object' && v !== null && Object.keys(v as object).length === 0);
  if (empty) return <div style={{ fontSize: 12, color: '#9ca3af' }}>—</div>;
  return (
    <pre style={{
      fontSize: 11, background: '#f7f7f7', padding: 8, margin: 0, borderRadius: 4,
      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', color: '#1f2937',
    }}>
      {JSON.stringify(v, null, 2)}
    </pre>
  );
}

/** One port row in the Inspector's Ports section: name · type · wired store ·
 *  contract meaning. Mirrors the card's port tooltip content, at rest. */
function PortDetail(props: {
  port: string;
  isOut: boolean;
  data: ProcessNodeData;
  semantic?: string;
}) {
  const { port, isOut, data, semantic } = props;
  const info = portInfo(port, isOut, {
    typeSchema: (isOut ? data.outputSchema : data.inputSchema) as Record<string, unknown> | undefined,
    portsSchema: isOut ? data.outputPortsSchema : data.inputPortsSchema,
    portsTarget: isOut ? data.outputPortsTarget : data.inputPortsTarget,
  });
  return (
    <div className="inspector-port" style={{
      padding: '6px 0', borderBottom: '1px solid #f1f5f9',
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 600, fontSize: 12, color: isOut ? '#0d9488' : '#4338ca' }}>
          {port}
        </span>
        <span style={{
          fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.04em',
          color: '#9ca3af', fontWeight: 700,
        }}>
          {info.direction}
        </span>
        {info.type && (
          <code title={info.fullType} style={{ fontSize: 11, color: '#64748b' }}>{info.type}</code>
        )}
      </div>
      {info.connectsTo && (
        <div style={{ fontSize: 11, marginTop: 2 }}>
          <span style={{ color: '#9ca3af' }}>→ </span>
          <code style={{ color: '#334155', wordBreak: 'break-all' }}>{info.connectsTo}</code>
        </div>
      )}
      {semantic && (
        <div style={{ fontSize: 11, color: '#64748b', marginTop: 2, fontStyle: 'italic' }}>
          {semantic}
        </div>
      )}
    </div>
  );
}

/** Comprehensive process inspector: contract prose, a full ports table (type +
 *  connection + meaning), config, math, symbols, assumptions, references — then
 *  the raw type/wiring schemas, collapsed, for completeness. */
function ProcessDetail(props: { details: ProcessNodeData }) {
  const d = props.details;
  const contract = deriveContract(d);
  const inputPorts = d.inputPorts ?? [];
  const outputPorts = d.outputPorts ?? [];
  const configEntries = Object.entries(d.config ?? {});
  const rawDescription = d.description;
  const hasDescription = typeof rawDescription === 'string' && rawDescription.trim().length > 0;

  return (
    <>
      {typeof d.address === 'string' && d.address && (
        <InspectorSection title="Address">
          <code style={{ fontSize: 11, color: '#374151', wordBreak: 'break-all' }}>
            {d.address}
          </code>
        </InspectorSection>
      )}

      {hasDescription && (
        <InspectorSection title="Description">
          <Prose text={rawDescription as string} />
        </InspectorSection>
      )}

      {(inputPorts.length > 0 || outputPorts.length > 0) && (
        <InspectorSection title={`Ports (${inputPorts.length} in / ${outputPorts.length} out)`}>
          {inputPorts.map((p) => (
            <PortDetail key={`i-${p}`} port={p} isOut={false} data={d} semantic={contract?.inputs?.[p]} />
          ))}
          {outputPorts.map((p) => (
            <PortDetail key={`o-${p}`} port={p} isOut data={d} semantic={contract?.outputs?.[p]} />
          ))}
        </InspectorSection>
      )}

      {configEntries.length > 0 && (
        <InspectorSection title="Config">
          <div>
            {configEntries.map(([k, v]) => (
              <div key={k} style={{
                display: 'flex', justifyContent: 'space-between', gap: 10,
                fontSize: 11, padding: '2px 0', fontFamily: 'ui-monospace, monospace',
              }}>
                <span style={{ color: '#4b5563' }}>{k}</span>
                <span style={{ color: '#1f2937', wordBreak: 'break-all', textAlign: 'right' }}>
                  {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                </span>
              </div>
            ))}
          </div>
        </InspectorSection>
      )}

      {contract && contract.math.length > 0 && (
        <InspectorSection title="Equations">
          <div style={{
            padding: '6px 8px', background: '#f8fafc', borderLeft: '2px solid #cbd5e1',
            borderRadius: 3, fontFamily: 'ui-monospace, monospace', fontSize: 11,
            color: '#1e293b', lineHeight: 1.6,
          }}>
            {contract.math.map((m, i) => <div key={i}>{m}</div>)}
          </div>
        </InspectorSection>
      )}

      {contract && Object.keys(contract.symbols).length > 0 && (
        <InspectorSection title="Symbols">
          <div style={{ fontSize: 11, color: '#475569', lineHeight: 1.5 }}>
            {Object.entries(contract.symbols).map(([s, meaning]) => (
              <div key={s}><em>{s}</em> — {meaning}</div>
            ))}
          </div>
        </InspectorSection>
      )}

      {contract && contract.assumptions.length > 0 && (
        <InspectorSection title="Assumptions">
          <ul style={{ fontSize: 11, color: '#475569', margin: 0, paddingLeft: 16, lineHeight: 1.5 }}>
            {contract.assumptions.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </InspectorSection>
      )}

      {contract && contract.references.length > 0 && (
        <InspectorSection title="References">
          <ul style={{ fontSize: 11, color: '#475569', margin: 0, paddingLeft: 16, lineHeight: 1.5 }}>
            {contract.references.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </InspectorSection>
      )}

      <InspectorSection title="Input type schema" defaultOpen={false}>
        <SchemaBlock value={d.inputSchema} />
      </InspectorSection>
      <InspectorSection title="Output type schema" defaultOpen={false}>
        <SchemaBlock value={d.outputSchema} />
      </InspectorSection>
      {(d.inputPortsSchema != null || d.outputPortsSchema != null) && (
        <InspectorSection title="Wiring (raw)" defaultOpen={false}>
          <SchemaBlock value={{ inputs: d.inputPortsSchema, outputs: d.outputPortsSchema }} />
        </InspectorSection>
      )}
    </>
  );
}

// src/panels/ConfigPanel.tsx — editable config as a left sidebar in Explore.
//
// Shows the composite's declared parameters as a compact "name (type) → value"
// form (descriptions are tucked behind a hover tooltip + click-to-expand ⓘ, so
// the panel stays scannable). "Apply" re-resolves the composite with the edited
// overrides and re-renders the Explore graph live; "Reset" reverts the fields to
// the composite's declared defaults. The "⤢ Full" hand-off to the full-window
// Setup & Run tab lives in the dock panel header (headerAction), not here. The
// bottom run bar runs with whatever config was last Applied.
import { useEffect, useMemo, useState } from 'react';
import type { ParameterDecl } from '../api';
import { resolveComposite, translateExternalConfig, configToComposite } from '../api';
import { _initialValue, _castFormValue } from './SetupRunPanel';

type FormValue = string | number | boolean;

/** A process/step/emitter node (has an address or a process-y _type) — NOT an
 *  editable input store. */
function _isProcessLike(v: unknown): boolean {
  if (!v || typeof v !== 'object') return false;
  const o = v as { _type?: unknown; address?: unknown };
  return o._type === 'process' || o._type === 'step'
    || typeof o.address === 'string';
}

/** The composite's editable INPUT stores: top-level state entries that are data
 *  (not processes/steps/emitters). These are what a run reads — the "Inputs". */
function _extractInputStores(state: unknown): Record<string, unknown> {
  if (!state || typeof state !== 'object') return {};
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(state as Record<string, unknown>)) {
    if (k.startsWith('_') || _isProcessLike(v)) continue;
    out[k] = v;
  }
  return out;
}

function _normType(t: string): 'int' | 'float' | 'bool' | 'list' | 'map' | 'string' {
  switch (t) {
    case 'int': case 'integer': return 'int';
    case 'float': case 'number': case 'double': return 'float';
    case 'bool': case 'boolean': return 'bool';
    case 'list': case 'list[string]': case 'array': return 'list';
    case 'map': case 'dict': case 'object': case 'json': return 'map';
    default: return 'string';
  }
}

// Structural markers hidden from the field editor (shown only in JSON mode).
// `_value` is edited via the typed-leaf path, not as a standalone row.
const HIDDEN_KEYS = new Set(['_type', '_control', '_figure', '_value']);

/** A typed-leaf store — `{ _type, _value, _figure }` — has a single editable
 *  value at `_value`, not a subtree. */
function _isTypedLeaf(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && '_value' in (v as object);
}

function _setNested(obj: unknown, path: string[], value: unknown): unknown {
  if (path.length === 0) return value;
  const [head, ...rest] = path;
  const src = (obj && typeof obj === 'object') ? obj as Record<string, unknown> : {};
  return { ...src, [head]: _setNested(src[head], rest, value) };
}

function _coerce(prev: unknown, next: string): unknown {
  if (typeof prev === 'number') { const n = Number(next); return Number.isFinite(n) ? n : prev; }
  if (typeof prev === 'boolean') return next === 'true';
  return next;
}

/** Structured, marker-free editor for the input-store tree: name→value rows for
 *  leaves, indented groups for nested nodes, with `_type`/`_control` hidden and
 *  the `contents` wrapper unwrapped — so a user edits "dna = 1", not plumbing. */
function InputTree({ node, path, onEdit, readOnly }: {
  node: unknown; path: string[];
  onEdit: (p: string[], v: unknown) => void; readOnly?: boolean;
}) {
  if (!node || typeof node !== 'object') return null;
  const entries = Object.entries(node as Record<string, unknown>).filter(([k]) => !HIDDEN_KEYS.has(k));
  return (
    <>
      {entries.map(([k, v]) => {
        if (k === 'contents' && v && typeof v === 'object') {
          return <InputTree key={k} node={v} path={[...path, k]} onEdit={onEdit} readOnly={readOnly} />;
        }
        // Typed-leaf store → one editable value at `_value` (hide _type/_figure).
        if (_isTypedLeaf(v)) {
          const lv = v._value;
          return (
            <label className="cfg-in-row" key={k}>
              <span className="cfg-in-name">{k}</span>
              <input className="cfg-in-input"
                type={typeof lv === 'number' ? 'number' : 'text'}
                step={typeof lv === 'number' ? 'any' : undefined}
                value={String(lv)} disabled={readOnly}
                onChange={(e) => onEdit([...path, k, '_value'], _coerce(lv, e.target.value))} />
            </label>
          );
        }
        if (v !== null && typeof v === 'object') {
          if (Object.keys(v as object).filter((ck) => !HIDDEN_KEYS.has(ck)).length === 0) return null;
          return (
            <div className="cfg-in-group" key={k}>
              <div className="cfg-in-group-h">{k}</div>
              <div className="cfg-in-children">
                <InputTree node={v} path={[...path, k]} onEdit={onEdit} readOnly={readOnly} />
              </div>
            </div>
          );
        }
        return (
          <label className="cfg-in-row" key={k}>
            <span className="cfg-in-name">{k}</span>
            {typeof v === 'boolean' ? (
              <select className="cfg-in-input" value={String(v)} disabled={readOnly}
                onChange={(e) => onEdit([...path, k], e.target.value === 'true')}>
                <option value="true">true</option><option value="false">false</option>
              </select>
            ) : (
              <input className="cfg-in-input"
                type={typeof v === 'number' ? 'number' : 'text'}
                step={typeof v === 'number' ? 'any' : undefined}
                value={String(v)} disabled={readOnly}
                onChange={(e) => onEdit([...path, k], _coerce(v, e.target.value))} />
            )}
          </label>
        );
      })}
    </>
  );
}

export interface ConfigPanelProps {
  compositeId: string | null;
  parameters: Record<string, ParameterDecl>;
  overrides: Record<string, unknown>;
  readOnly?: boolean;
  /** Apply: hand back the new overrides + resolved state so App re-renders the
   *  graph and remembers the overrides (the run bar runs with them). */
  onApplied: (overrides: Record<string, unknown>, state: unknown) => void;
  /** The current composite state — its input stores seed the Inputs editor. */
  state?: unknown;
  /** Apply Inputs: hand back the full state with edited input stores merged in,
   *  so App re-renders the graph (values manifest) and the JSON reflects it. */
  onInputsApplied?: (state: unknown) => void;
  /** View as bigraph: hand back the document rendered from an external config's
   *  OWN declared structure (via /api/config-to-composite) — NOT a build, and
   *  distinct from Apply/onApplied (which resolves this composite's config). */
  onBigraphDocument?: (state: unknown) => void;
}

export function ConfigPanel(props: ConfigPanelProps) {
  const seed = (useDefaults: boolean) => Object.fromEntries(
    Object.entries(props.parameters).map(([k, pdef]) => [
      k, _initialValue(pdef, useDefaults ? undefined : props.overrides[k]),
    ])
  );
  const [values, setValues] = useState<Record<string, FormValue>>(() => seed(false));
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  // Which fields have their description expanded (click ⓘ). Hover shows the
  // native title tooltip regardless.
  const [descOpen, setDescOpen] = useState<Record<string, boolean>>({});

  // Re-seed whenever the composite (its params/overrides) changes.
  useEffect(() => {
    setValues(seed(false));
    setError(null);
    setApplied(false);
    setDescOpen({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.parameters, props.overrides]);

  const paramKeys = Object.keys(props.parameters);

  function buildOverrides(): Record<string, unknown> {
    const ov: Record<string, unknown> = { ...props.overrides };
    for (const [k, pdef] of Object.entries(props.parameters)) {
      ov[k] = _castFormValue(pdef, values[k]);
    }
    return ov;
  }

  async function handleApply() {
    if (!props.compositeId) return;
    setApplying(true);
    setError(null);
    setApplied(false);
    try {
      const ov = buildOverrides();
      const res = await resolveComposite(props.compositeId, ov);
      if (res.error) { setError(res.error); return; }
      props.onApplied(ov, res.state);
      setApplied(true);
    } catch (e: unknown) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setApplying(false);
    }
  }

  function handleReset() {
    setValues(seed(true));
    setApplied(false);
    setError(null);
  }

  // ---- External config (item 86) ------------------------------------------
  // Upload or paste an arbitrary JSON document; the server matches its keys
  // onto this composite's own declared params and returns them adapted. The
  // result populates the SAME `values` state the per-field form edits, so the
  // existing Apply button (unchanged) is what actually applies it — this is
  // an alternate way to SET the fields, not a second, parallel data path.
  const [extConfigOpen, setExtConfigOpen] = useState(false);
  const [extConfigText, setExtConfigText] = useState('');
  const [extConfigApplying, setExtConfigApplying] = useState(false);
  const [extConfigError, setExtConfigError] = useState<string | null>(null);
  const [extConfigResult, setExtConfigResult] = useState<string | null>(null);
  const [viewingBigraph, setViewingBigraph] = useState(false);

  function handleExtConfigFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    file.text().then(setExtConfigText).catch((err) => setExtConfigError(String(err)));
  }

  /** Parse + validate `extConfigText` as a JSON object, setting `extConfigError`
   *  on failure. Shared by "Apply config" (match onto this composite's params)
   *  and "View as bigraph" (render the config's own declared structure). */
  function _parseExtConfigText(): Record<string, unknown> | null {
    let parsed: unknown;
    try {
      parsed = JSON.parse(extConfigText);
    } catch (e) {
      setExtConfigError('Not valid JSON: ' + (e instanceof Error ? e.message : String(e)));
      return null;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setExtConfigError('Config must be a JSON object (not an array or scalar)');
      return null;
    }
    return parsed as Record<string, unknown>;
  }

  async function handleApplyExtConfig() {
    if (!props.compositeId) return;
    setExtConfigError(null);
    setExtConfigResult(null);
    const parsed = _parseExtConfigText();
    if (!parsed) return;
    setExtConfigApplying(true);
    try {
      const res = await translateExternalConfig(props.compositeId, parsed as Record<string, unknown>);
      setValues((prev) => {
        const next = { ...prev };
        for (const [k, v] of Object.entries(res.params)) {
          const pdef = props.parameters[k];
          if (pdef) next[k] = _initialValue(pdef, v);
        }
        return next;
      });
      setApplied(false);
      let msg = `✓ set ${Object.keys(res.params).length} field(s) — click Apply to use them`;
      if (res.unmatched.length) msg += `. Ignored (no matching param): ${res.unmatched.join(', ')}`;
      setExtConfigResult(msg);
    } catch (e) {
      setExtConfigError(e instanceof Error ? e.message : String(e));
    } finally {
      setExtConfigApplying(false);
    }
  }

  /** View as bigraph: render the config's OWN declared structure — no build,
   *  distinct from "Apply config" (which matches keys onto THIS composite's
   *  params) and from Apply/resolveComposite. */
  async function handleViewAsBigraph() {
    setExtConfigError(null);
    setExtConfigResult(null);
    const parsed = _parseExtConfigText();
    if (!parsed) return;
    setViewingBigraph(true);
    try {
      const res = await configToComposite(parsed);
      props.onBigraphDocument?.(res.state);
      setExtConfigResult('✓ Rendered as bigraph document.');
    } catch (e) {
      setExtConfigError(e instanceof Error ? e.message : String(e));
    } finally {
      setViewingBigraph(false);
    }
  }

  // ---- Inputs (editable input-store state) --------------------------------
  const inputStores = useMemo(() => _extractInputStores(props.state), [props.state]);
  const inputKeys = Object.keys(inputStores);
  const [inputsText, setInputsText] = useState<string>(() => JSON.stringify(inputStores, null, 2));
  const [inputsErr, setInputsErr] = useState<string | null>(null);
  const [inputsApplied, setInputsApplied] = useState(false);
  const [inputsMode, setInputsMode] = useState<'fields' | 'json'>('fields');
  // Selected Configure/Inputs tab; null = "not chosen yet" → derive a sensible
  // default in render (Configure if the composite has params, else Inputs).
  const [tabSel, setTabSel] = useState<'config' | 'inputs' | null>(null);
  // Parsed view of the current inputs text for the structured field editor.
  let inputsObj: unknown = {};
  try { inputsObj = JSON.parse(inputsText); } catch { /* JSON mode shows the error */ }
  const handleTreeEdit = (p: string[], v: unknown) => {
    setInputsText(JSON.stringify(_setNested(inputsObj, p, v), null, 2));
    setInputsApplied(false); setInputsErr(null);
  };
  // Re-seed the Inputs editor whenever the input stores change (new composite,
  // or a config Apply that reshaped the state — inputs follow config).
  useEffect(() => {
    setInputsText(JSON.stringify(inputStores, null, 2));
    setInputsErr(null);
    setInputsApplied(false);
  }, [inputStores]);

  function handleApplyInputs() {
    try {
      const parsed = JSON.parse(inputsText) as Record<string, unknown>;
      const base = (props.state && typeof props.state === 'object')
        ? { ...(props.state as Record<string, unknown>) } : {};
      for (const k of Object.keys(parsed)) base[k] = parsed[k];
      props.onInputsApplied?.(base);
      setInputsErr(null);
      setInputsApplied(true);
    } catch (e) {
      setInputsErr(String(e instanceof Error ? e.message : e));
    }
  }

  // Which section is showing. A composite with no declared params opens straight
  // on Inputs (no empty Configure tab); otherwise Configure leads. `tabSel` is
  // the user's explicit choice, `tab` the effective one (derived when unset).
  const hasConfig = paramKeys.length > 0;
  const tab: 'config' | 'inputs' = tabSel ?? (hasConfig ? 'config' : 'inputs');

  return (
    <div className="cfg-panel">
      {props.readOnly && (
        <p className="cfg-note">Read-only preview — editing config requires a live dashboard.</p>
      )}

      {/* Tab switcher — jump between Configure and Inputs without scrolling the
          whole stacked panel. Sticky (see .cfg-tabs) so it stays reachable. */}
      <div className="cfg-tabs" role="tablist">
        {hasConfig && (
          <button type="button" role="tab" aria-selected={tab === 'config'}
            className={'cfg-tab' + (tab === 'config' ? ' cfg-tab-active' : '')}
            onClick={() => setTabSel('config')}>
            Configure{paramKeys.length ? ' · ' + paramKeys.length : ''}
          </button>
        )}
        <button type="button" role="tab" aria-selected={tab === 'inputs'}
          className={'cfg-tab' + (tab === 'inputs' ? ' cfg-tab-active' : '')}
          onClick={() => setTabSel('inputs')}>
          Inputs{inputKeys.length ? ' · ' + inputKeys.length : ''}
        </button>
      </div>

      {/* Configure — only when the composite actually declares parameters, so a
          zero-param composite opens straight on Inputs (no dead tab/note). */}
      {hasConfig && tab === 'config' && (
        <>
        {/* Load from JSON config — pinned to the TOP of Configure so it's the
            first thing you reach (was previously buried below the fields). */}
        <div className="cfg-extconfig-top">
          <button type="button" className={'cfg-json-toggle cfg-extconfig-toggle' + (extConfigOpen ? ' open' : '')}
            onClick={() => setExtConfigOpen((o) => !o)} disabled={props.readOnly}
            title="Upload or paste a JSON config document to set several parameters at once">
            📄 Load from JSON config
          </button>
          {extConfigOpen && (
            <div className="cfg-extconfig">
              <input type="file" accept=".json,application/json" disabled={props.readOnly}
                onChange={handleExtConfigFile} />
              <textarea
                className="sr-input cfg-input cfg-extconfig-box"
                spellCheck={false}
                rows={Math.min(12, Math.max(4, extConfigText.split('\n').length))}
                placeholder="{ …a JSON config document… } — matched against this composite's declared params"
                value={extConfigText}
                disabled={props.readOnly}
                onChange={(e) => { setExtConfigText(e.target.value); setExtConfigError(null); setExtConfigResult(null); }}
              />
              {extConfigError && <div className="cfg-error">{extConfigError}</div>}
              {extConfigResult && !extConfigError && <div className="cfg-applied">{extConfigResult}</div>}
              <div className="cfg-actionbar">
                <button className="sr-run-btn cfg-apply-btn" onClick={handleApplyExtConfig}
                  disabled={extConfigApplying || props.readOnly || !props.compositeId || !extConfigText.trim()}>
                  {extConfigApplying ? 'Matching…' : 'Apply config'}
                </button>
                <button type="button" className="cfg-reset-btn" onClick={handleViewAsBigraph}
                  disabled={viewingBigraph || props.readOnly || !extConfigText.trim() || !props.onBigraphDocument}
                  title="Render this config's own declared structure as a bigraph document — no build">
                  {viewingBigraph ? 'Rendering…' : 'View as bigraph'}
                </button>
              </div>
            </div>
          )}
        </div>
        <div className="cfg-fields">
          {paramKeys.map((k) => {
            const pdef = props.parameters[k];
            const id = `explore-cfg-${k}`;
            const val = values[k];
            const hasDesc = !!pdef.description;
            const onChange = (v: FormValue) => { setValues((prev) => ({ ...prev, [k]: v })); setApplied(false); };
            return (
              <div className="cfg-field" key={k}>
                <div className="cfg-field-head" title={pdef.description || undefined}>
                  <code className="cfg-name">{k}</code>
                  <span className="cfg-type">{pdef.type}</span>
                  {hasDesc && (
                    <button
                      type="button"
                      className={'cfg-info' + (descOpen[k] ? ' open' : '')}
                      title={descOpen[k] ? 'Hide description' : 'Show description'}
                      aria-label="Toggle description"
                      onClick={() => setDescOpen((p) => ({ ...p, [k]: !p[k] }))}
                    >ⓘ</button>
                  )}
                </div>
                {Array.isArray(pdef.choices) && pdef.choices.length > 0 ? (
                  <select id={id} className="sr-input cfg-input" value={String(val)} disabled={props.readOnly}
                    onChange={(e) => onChange(e.target.value)}>
                    {pdef.choices.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                ) : _normType(pdef.type) === 'list' ? (
                  <textarea id={id} className="sr-input cfg-input" rows={Math.max(2, String(val).split('\n').length)}
                    value={String(val)} disabled={props.readOnly}
                    onChange={(e) => onChange(e.target.value)} placeholder="one item per line" />
                ) : _normType(pdef.type) === 'bool' ? (
                  <select id={id} className="sr-input cfg-input" value={String(val)} disabled={props.readOnly}
                    onChange={(e) => onChange(e.target.value === 'true')}>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <input id={id} className="sr-input cfg-input"
                    type={_normType(pdef.type) === 'int' || _normType(pdef.type) === 'float' ? 'number' : 'text'}
                    step={_normType(pdef.type) === 'float' ? 'any' : _normType(pdef.type) === 'int' ? '1' : undefined}
                    value={String(val)} disabled={props.readOnly}
                    onChange={(e) => onChange(e.target.value)} />
                )}
                {hasDesc && descOpen[k] && <div className="cfg-desc">{pdef.description}</div>}
              </div>
            );
          })}
        </div>
        {error && <div className="cfg-error">Could not apply: {error}</div>}
        {applied && !error && <div className="cfg-applied">✓ Graph rebuilt with this config.</div>}
        <div className="cfg-actionbar">
          <button className="sr-run-btn cfg-apply-btn" onClick={handleApply}
            disabled={applying || props.readOnly || !props.compositeId}>
            {applying ? 'Applying…' : 'Apply'}
          </button>
          <button className="cfg-reset-btn" onClick={handleReset} disabled={applying}
            title="Revert fields to the composite's declared defaults">
            Reset
          </button>
        </div>
        </>
      )}

      {/* ---- Inputs: the composite's editable input-store state, as a
           marker-free field editor (JSON toggle for power users). Applied
           SEPARATELY (inputs can follow config); re-renders Explore live. */}
      {tab === 'inputs' && (
      <>
      <div className="cfg-group-h cfg-group-h-inputs">
        <span>Inputs</span>
        {inputKeys.length > 0 && (
          <button type="button" className="cfg-json-toggle"
            onClick={() => setInputsMode((m) => (m === 'fields' ? 'json' : 'fields'))}
            title={inputsMode === 'fields' ? 'Edit as raw JSON' : 'Edit as fields'}>
            {inputsMode === 'fields' ? '{ } JSON' : '▤ Fields'}
          </button>
        )}
      </div>
      {inputKeys.length === 0 ? (
        <p className="cfg-note">This composite has no editable input stores.</p>
      ) : (
        <>
          <p className="cfg-note cfg-inputs-hint">
            Input-store values a run reads — edit and Apply to see them on the graph.
          </p>
          {inputsMode === 'fields' ? (
            <div className="cfg-in-tree">
              <InputTree node={inputsObj} path={[]} onEdit={handleTreeEdit} readOnly={props.readOnly} />
            </div>
          ) : (
            <textarea
              className="sr-input cfg-input cfg-inputs-json"
              spellCheck={false}
              rows={Math.min(18, Math.max(4, inputsText.split('\n').length))}
              value={inputsText}
              disabled={props.readOnly}
              onChange={(e) => { setInputsText(e.target.value); setInputsApplied(false); setInputsErr(null); }}
            />
          )}
          {inputsErr && <div className="cfg-error">Invalid JSON: {inputsErr}</div>}
          {inputsApplied && !inputsErr && <div className="cfg-applied">✓ Graph updated with these inputs.</div>}
          <div className="cfg-actionbar">
            <button className="sr-run-btn cfg-apply-btn" onClick={handleApplyInputs}
              disabled={props.readOnly || !props.onInputsApplied}>
              Apply Inputs
            </button>
            <button className="cfg-reset-btn"
              onClick={() => { setInputsText(JSON.stringify(inputStores, null, 2)); setInputsApplied(false); setInputsErr(null); }}
              title="Revert the input stores to their current values">
              Reset
            </button>
          </div>
        </>
      )}
      </>
      )}
    </div>
  );
}

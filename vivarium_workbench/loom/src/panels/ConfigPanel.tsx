// src/panels/ConfigPanel.tsx — editable config as a left sidebar in Explore.
//
// Shows the composite's declared parameters as a compact "name (type) → value"
// form (descriptions are tucked behind a hover tooltip + click-to-expand ⓘ, so
// the panel stays scannable). "Apply" re-resolves the composite with the edited
// overrides and re-renders the Explore graph live; "Reset" reverts the fields to
// the composite's declared defaults. The "⤢ Full" hand-off to the full-window
// Setup & Run tab lives in the dock panel header (headerAction), not here. The
// bottom run bar runs with whatever config was last Applied.
import { useEffect, useState } from 'react';
import type { ParameterDecl } from '../api';
import { resolveComposite } from '../api';
import { _initialValue, _castFormValue } from './SetupRunPanel';

type FormValue = string | number | boolean;

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

export interface ConfigPanelProps {
  compositeId: string | null;
  parameters: Record<string, ParameterDecl>;
  overrides: Record<string, unknown>;
  readOnly?: boolean;
  /** Apply: hand back the new overrides + resolved state so App re-renders the
   *  graph and remembers the overrides (the run bar runs with them). */
  onApplied: (overrides: Record<string, unknown>, state: unknown) => void;
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

  return (
    <div className="cfg-panel">
      {props.readOnly && (
        <p className="cfg-note">Read-only preview — editing config requires a live dashboard.</p>
      )}

      {paramKeys.length === 0 ? (
        <p className="cfg-note">This composite declares no config parameters.</p>
      ) : (
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
      )}

      {error && <div className="cfg-error">Could not apply: {error}</div>}
      {applied && !error && <div className="cfg-applied">✓ Graph rebuilt with this config.</div>}

      {paramKeys.length > 0 && (
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
      )}
    </div>
  );
}

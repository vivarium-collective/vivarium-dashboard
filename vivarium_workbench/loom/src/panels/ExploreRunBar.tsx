// src/panels/ExploreRunBar.tsx — slim run bar pinned along the bottom of Explore.
//
// Lets you run the composite without leaving the graph. Runs with the config
// last Applied in the Config sidebar (props.overrides). Full parameter editing +
// richer run feedback live in the full-window Setup & Run tab; this bar is the
// discrete quick-run. Shares run semantics with SetupRunPanel via useCompositeRun.
import { useState } from 'react';
import { useCompositeRun, phaseLabel } from '../hooks/useCompositeRun';
import { TopoTransport } from './TopoTransport';

export interface ExploreRunBarProps {
  compositeId: string | null;
  overrides: Record<string, unknown>;
  emitSet: Set<string>;
  runContext?: string;
  defaultSteps?: number;
  runKind?: 'temporal' | 'workflow';
  readOnly?: boolean;
  onTrajectory?: (rows: Array<{ step: number; time?: number; state: Record<string, unknown> }>) => void;
  onVizHtml?: (vizHtml: Record<string, { html: string }> | null) => void;
  onCompleted?: () => void;
  onRunState?: (s: { runId: string | null; downloadable: boolean }) => void;
  // Playback transport — folded INTO this bar so run + step are one control.
  // Present (frameIdx != null) only once a run has produced a steppable trajectory.
  transport?: {
    frameIdx: number;
    frameCount: number;
    frameTime?: number;
    playing: boolean;
    onPrev: () => void;
    onNext: () => void;
    onToggle: () => void;
    onScrub: (i: number) => void;
    onExit: () => void;
  } | null;
  /** Top-level stores the run can record; the emit chip toggles them. */
  emitCandidates?: string[];
  onToggleEmit?: (key: string) => void;
}

export function ExploreRunBar(props: ExploreRunBarProps) {
  const run = useCompositeRun({
    compositeId: props.compositeId,
    emitSet: props.emitSet,
    runContext: props.runContext,
    defaultSteps: props.defaultSteps,
    runKind: props.runKind,
    readOnly: props.readOnly,
    onTrajectory: props.onTrajectory,
    onVizHtml: props.onVizHtml,
    onCompleted: props.onCompleted,
    onRunState: props.onRunState,
    buildOverrides: () => props.overrides,
  });

  const hasTransport = !!props.transport;
  const isSteps = run.stepMode === 'steps';
  const [whyOpen, setWhyOpen] = useState(false);
  const [emitOpen, setEmitOpen] = useState(false);
  const emitLabel = (k: string) => k.split('.').pop() || k;
  const failText = (run.status?.status === 'failed' || run.status?.status === 'orphaned')
    ? (run.status?.error?.trim() || (run.status?.log_path ? 'See log: ' + run.status.log_path : ''))
    : '';
  const whyText = run.startError || failText;
  return (
    <div className="explore-runbar">
      {/* Kind: a step network advances in discrete integer steps (steppable one
          at a time); a temporal composite runs over continuous time. */}
      <span className={'explore-runbar-kind' + (isSteps ? ' is-steps' : ' is-time')}
        title={isSteps
          ? 'Step network — advances in discrete integer steps you can step through one at a time.'
          : 'Temporal — runs its processes over continuous time.'}>
        {isSteps ? '◇ steps' : '◷ time'}
      </span>
      <label className="explore-runbar-dur"
        title={isSteps
          ? 'Number of discrete steps to advance — set 1 to step one at a time, then use ▶❘.'
          : 'How long to advance the composite, in continuous time units.'}>
        {isSteps ? 'Steps' : 'Duration'}{' '}
        <input
          type="number"
          min={isSteps ? 1 : 0} max={10000}
          step={isSteps ? 1 : 'any'}
          value={run.steps}
          onChange={(e) => { const v = parseFloat(e.target.value); run.setSteps(Number.isFinite(v) && v > 0 ? v : 1); }}
          disabled={run.isRunning}
        />
      </label>
      <button className="sr-run-btn explore-run-btn" onClick={run.handleRun} disabled={run.isRunning || !run.canRun}>
        {run.isRunning ? 'Running…' : hasTransport ? '↻ Re-run' : (isSteps ? '▶ Run steps' : '▶ Run')}
      </button>

      {/* Run + step are ONE control: once a run yields a steppable trajectory the
          playback transport lives right here in the run bar. */}
      {props.transport && (
        <>
          <span className="explore-runbar-div" aria-hidden="true" />
          <TopoTransport {...props.transport} />
        </>
      )}

      {/* Inline status: progress bar while simulating, phase/label otherwise. */}
      {run.isRunning && run.status && (
        run.status.phase && run.status.phase !== 'simulating' ? (
          <span className="explore-runbar-status">
            <span className="sr-phase-dot" /> {phaseLabel(run.status.phase)}…
          </span>
        ) : (
          <span className="explore-runbar-progress" title={`step ${run.status.progress_step} of ${run.status.n_steps ?? '?'}`}>
            <span className="explore-runbar-track"><span className="explore-runbar-fill" style={{ width: `${run.pct}%` }} /></span>
            <span className="explore-runbar-status">
              {run.isWorkflow ? 'Running' : `step ${run.status.progress_step}/${run.status.n_steps ?? '?'}`}
            </span>
          </span>
        )
      )}
      {run.isRunning && !run.status && <span className="explore-runbar-status">Starting…</span>}
      {run.status?.status === 'completed' && <span className="explore-runbar-done">✓ complete</span>}
      {(run.status?.status === 'failed' || run.status?.status === 'orphaned') && (
        <span className="explore-runbar-fail">
          Run {run.status.status}
          {(run.status.error || run.status.log_path) && (
            <button type="button" className="explore-runbar-why"
              onClick={() => setWhyOpen((o) => !o)}>{whyOpen ? 'hide' : 'why?'}</button>
          )}
        </span>
      )}
      {run.startError && <span className="explore-runbar-fail">Could not start run
        <button type="button" className="explore-runbar-why"
          onClick={() => setWhyOpen((o) => !o)}>{whyOpen ? 'hide' : 'why?'}</button>
      </span>}
      {whyOpen && whyText && (
        <div className="explore-runbar-why-detail">{whyText}</div>
      )}

      {!run.isRunning && !run.startError && (
        run.inInvestigation ? (
          <span className="explore-runbar-emit">Running is managed by the Study controls.</span>
        ) : props.readOnly ? (
          <span className="explore-runbar-emit">Read-only preview — running requires a live dashboard.</span>
        ) : (
          <div className="explore-runbar-emit-wrap">
            <button type="button" className="explore-runbar-emit-btn"
              onClick={() => setEmitOpen((o) => !o)}
              disabled={!props.emitCandidates || props.emitCandidates.length === 0}
              title="Choose which stores to record (emit) when this composite runs">
              emit: {props.emitSet.size === 0 ? 'none' : Array.from(props.emitSet).map(emitLabel).join(', ')} ▾
            </button>
            {emitOpen && props.emitCandidates && (
              <div className="explore-runbar-emit-pop">
                <div className="explore-runbar-emit-pop-h">Record on run</div>
                {props.emitCandidates.length === 0
                  ? <div className="explore-runbar-emit-empty">No stores to record.</div>
                  : props.emitCandidates.map((k) => (
                    <label className="explore-runbar-emit-opt" key={k}>
                      <input type="checkbox" checked={props.emitSet.has(k)}
                        onChange={() => props.onToggleEmit?.(k)} />
                      {emitLabel(k)}
                    </label>
                  ))}
              </div>
            )}
          </div>
        )
      )}
    </div>
  );
}

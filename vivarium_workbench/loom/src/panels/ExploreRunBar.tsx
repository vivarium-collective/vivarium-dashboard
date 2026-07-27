// src/panels/ExploreRunBar.tsx — slim run bar pinned along the bottom of Explore.
//
// Lets you run the composite without leaving the graph. Runs with the config
// last Applied in the Config sidebar (props.overrides). Full parameter editing +
// richer run feedback live in the full-window Setup & Run tab; this bar is the
// discrete quick-run. Shares run semantics with SetupRunPanel via useCompositeRun.
import { useCompositeRun, phaseLabel } from '../hooks/useCompositeRun';

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

  return (
    <div className="explore-runbar">
      {!run.isWorkflow && (
        <label className="explore-runbar-dur" title="How long to advance the composite, in time units">
          Duration{' '}
          <input
            type="number" min={0} max={10000} step="any" value={run.steps}
            onChange={(e) => { const v = parseFloat(e.target.value); run.setSteps(Number.isFinite(v) && v > 0 ? v : 1); }}
            disabled={run.isRunning}
          />
        </label>
      )}
      <button className="sr-run-btn explore-run-btn" onClick={run.handleRun} disabled={run.isRunning || !run.canRun}>
        {run.isRunning ? (run.isWorkflow ? 'Running…' : 'Running…') : '▶ Run'}
      </button>

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
      {run.status?.status === 'completed' && <span className="explore-runbar-done">✓ complete — see Results</span>}
      {(run.status?.status === 'failed' || run.status?.status === 'orphaned') && (
        <span className="explore-runbar-fail">
          Run {run.status.status}
          {(run.status.error || run.status.log_path) && (
            <button
              type="button"
              className="explore-runbar-why"
              title={run.status.error ? run.status.error.trim().slice(-1200) : `See log: ${run.status.log_path}`}
              onClick={() => alert(run.status?.error?.trim() || `See log: ${run.status?.log_path}`)}
            >why?</button>
          )}
        </span>
      )}
      {run.startError && <span className="explore-runbar-fail" title={run.startError}>Could not start run
        <button type="button" className="explore-runbar-why" title={run.startError}
          onClick={() => alert(run.startError)}>why?</button>
      </span>}

      {!run.isRunning && !run.startError && (
        <span className="explore-runbar-emit">
          {run.inInvestigation
            ? 'Running is managed by the Study controls.'
            : props.readOnly
              ? 'Read-only preview — running requires a live dashboard.'
              : <>emit: {props.emitSet.size === 0 ? 'none — pick stores in Explore' : Array.from(props.emitSet).join(', ')}</>}
        </span>
      )}
    </div>
  );
}

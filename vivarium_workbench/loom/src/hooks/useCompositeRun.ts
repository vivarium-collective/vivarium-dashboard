// src/hooks/useCompositeRun.ts — composite run lifecycle (start + poll + progress).
//
// Extracted so more than one surface can drive a run of the same composite: the
// full-window Setup & Run tab (SetupRunPanel) keeps its own copy, while the
// Explore tab's bottom run bar (ExploreRunBar) uses this hook. Both share the
// same detached-run + polling semantics: a run outlives the tab, and a dropped
// poll just retries on the next tick.
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  postRunComplete, startRun, fetchRunStatus, fetchRunTrajectory,
  type RunStatus,
} from '../api';

type TrajectoryRow = { step: number; time?: number; state: Record<string, unknown> };

const ACTIVE_RUN_KEY = 'bigraph-loom:active-run';
const POLL_MS = 1500;

/** Human label for a run phase (backend emits lowercase stage names). */
export function phaseLabel(phase: string): string {
  return phase.charAt(0).toUpperCase() + phase.slice(1);
}

export interface UseCompositeRunArgs {
  compositeId: string | null;
  emitSet: Set<string>;
  runContext?: string;
  defaultSteps?: number;
  runKind?: 'temporal' | 'workflow';
  readOnly?: boolean;
  onTrajectory?: (rows: TrajectoryRow[]) => void;
  onVizHtml?: (vizHtml: Record<string, { html: string }> | null) => void;
  onCompleted?: () => void;
  onRunState?: (s: { runId: string | null; downloadable: boolean }) => void;
  /** Returns the config overrides to run with — evaluated at click time so the
   *  caller can hand over the latest applied/edited values. */
  buildOverrides?: () => Record<string, unknown>;
}

export function useCompositeRun(args: UseCompositeRunArgs) {
  const [steps, setSteps] = useState(args.defaultSteps ?? 5);
  useEffect(() => {
    if (args.defaultSteps != null) setSteps(args.defaultSteps);
  }, [args.compositeId, args.defaultSteps]);

  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const inInvestigation = !!(args.runContext && args.runContext.startsWith('investigation:'));
  const canRun = !!args.compositeId && !inInvestigation && !args.readOnly;
  const isRunning = status?.status === 'running' || (!!runId && !status);
  const isWorkflow = args.runKind === 'workflow';

  // Refs so the polling closure always sees the latest callbacks without being
  // recreated (same pattern as SetupRunPanel).
  const onTrajectoryRef = useRef(args.onTrajectory);
  const onVizHtmlRef = useRef(args.onVizHtml);
  const onCompletedRef = useRef(args.onCompleted);
  const onRunStateRef = useRef(args.onRunState);
  const buildOverridesRef = useRef(args.buildOverrides);
  useEffect(() => { onTrajectoryRef.current = args.onTrajectory; }, [args.onTrajectory]);
  useEffect(() => { onVizHtmlRef.current = args.onVizHtml; }, [args.onVizHtml]);
  useEffect(() => { onCompletedRef.current = args.onCompleted; }, [args.onCompleted]);
  useEffect(() => { onRunStateRef.current = args.onRunState; }, [args.onRunState]);
  useEffect(() => { buildOverridesRef.current = args.buildOverrides; }, [args.buildOverrides]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadTrajectory = useCallback(async (id: string) => {
    try {
      const traj = await fetchRunTrajectory(id);
      onTrajectoryRef.current?.(traj.trajectory);
    } catch {
      /* trajectory not ready yet — next poll retries */
    }
  }, []);

  const beginPolling = useCallback((id: string) => {
    stopPolling();
    const tick = async () => {
      let s: RunStatus;
      try {
        s = await fetchRunStatus(id);
      } catch {
        return; // transient — retry next tick
      }
      setStatus(s);
      onRunStateRef.current?.({ runId: id, downloadable: s.downloadable ?? false });
      if (s.viz_html) onVizHtmlRef.current?.(s.viz_html);
      if (s.status === 'running') {
        void loadTrajectory(id);
      } else {
        stopPolling();
        void loadTrajectory(id);
        sessionStorage.removeItem(ACTIVE_RUN_KEY);
        if (s.status === 'completed' && args.compositeId) {
          postRunComplete(id, args.compositeId);
          onCompletedRef.current?.();
        }
      }
    };
    void tick();
    pollRef.current = setInterval(tick, POLL_MS);
  }, [stopPolling, loadTrajectory, args.compositeId]);

  // Re-attach to an in-flight run after an iframe reload / network blip.
  useEffect(() => {
    const raw = sessionStorage.getItem(ACTIVE_RUN_KEY);
    if (!raw) return;
    try {
      const saved = JSON.parse(raw) as { run_id: string; composite_id: string };
      if (saved.composite_id === args.compositeId && saved.run_id) {
        setRunId(saved.run_id);
        beginPolling(saved.run_id);
      }
    } catch {
      sessionStorage.removeItem(ACTIVE_RUN_KEY);
    }
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [args.compositeId]);

  const handleRun = useCallback(async () => {
    if (!args.compositeId) {
      setStartError('No composite id — pop-out windows need ?id=<dotted-ref> in the URL.');
      return;
    }
    setStartError(null);
    setStatus(null);
    onTrajectoryRef.current?.([]);
    onVizHtmlRef.current?.(null);
    const overrides = buildOverridesRef.current?.() ?? {};
    try {
      const res = await startRun({
        id: args.compositeId,
        steps: isWorkflow ? 1 : steps,
        emit_paths: Array.from(args.emitSet),
        overrides: Object.keys(overrides).length > 0 ? overrides : undefined,
      });
      setRunId(res.run_id);
      sessionStorage.setItem(ACTIVE_RUN_KEY, JSON.stringify({
        run_id: res.run_id, composite_id: args.compositeId,
      }));
      beginPolling(res.run_id);
    } catch (e: unknown) {
      setStartError(String(e instanceof Error ? e.message : e));
    }
  }, [args.compositeId, args.emitSet, isWorkflow, steps, beginPolling]);

  const pct = status && status.n_steps
    ? Math.min(100, Math.round((status.progress_step / status.n_steps) * 100))
    : 0;

  return {
    steps, setSteps, runId, status, startError,
    isRunning, isWorkflow, canRun, inInvestigation, pct, handleRun,
  };
}

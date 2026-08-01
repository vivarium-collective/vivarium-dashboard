"""Investigation-level post-sim analyses: after all member studies run, execute
any `analyses:` the investigation.yaml declares (e.g. a cross-config matrix that
aggregates each member study's verdict). Additive — a no-op when unset.

``_dispatch_analysis`` is deliberately NOT wired to the ``run_study_analyses``
env-worker capability yet — see its docstring and
``.superpowers/sdd/2026-08-01-investigation-execution-hook-phase-a/task-3-report.md``
for why: that capability structurally requires a real parquet sweep directory
to produce anything, which an investigation-level analysis (aggregating
already-computed per-study verdicts, not raw sim history) does not have.
"""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _dispatch_analysis(ws_root, inv_slug, entry, study_results) -> list[str]:
    """Dispatch one investigation-level ``analyses:`` entry.

    NOT IMPLEMENTED — the existing ``run_study_analyses`` env-worker
    capability (``vivarium_workbench/env_worker.py:_run_study_analyses``,
    dispatched via ``study_run_post.run_study_analyses`` at
    ``study_run_post.py:230``) cannot accept an investigation-scoped call.

    Concretely: that capability's only path to producing output is
    ``v2ecoli.workflow.analysis_runner.run_analyses(sweep_dir, ...)``, which
    first calls ``build_cell_records(sweep_dir)`` — a glob over
    ``sweep_dir/**/history/**/*.pq`` (a single study's parquet emitter
    sweep). An investigation report dir
    (``WorkspacePaths.load(ws).report_dir(inv_slug)``) has no such parquet
    tree, so ``build_cell_records`` returns ``{}``, ``group_for_scale``
    returns ``{}`` for every scale, and the per-analysis group loop
    (``analysis_runner.py``, ``for gkey in groups:``) never executes — the
    declared analysis is silently never invoked and the call returns
    ``{"written": [], "errors": []}`` with no signal that anything went
    wrong. This is true even for an analysis like v2ecoli's
    ``comparison_matrix`` (``scale = "single"``) whose real input is a
    ``config_verdicts`` dict passed as Step *config* (each member study's
    already-graded verdict, exactly what ``study_results`` would carry) —
    it never gets that far because there is no sweep_dir to derive groups
    from.

    Reusing ``run_study_analyses`` here would require either fabricating a
    fake study parquet sweep (explicitly disallowed) or a worker-side
    capability change (e.g. an investigation-scoped code path that skips
    ``build_cell_records``/group iteration and invokes the Analysis directly
    with ``config_verdicts`` config) — out of scope for this task. See the
    BLOCKED report for the follow-up.
    """
    raise NotImplementedError(
        "investigation-scoped worker dispatch — see BLOCKED report at "
        ".superpowers/sdd/2026-08-01-investigation-execution-hook-phase-a/"
        "task-3-report.md"
    )


def run_investigation_analyses(ws_root, inv_slug, spec, study_results):
    """Run every ``spec.analyses[]`` entry declared on an investigation.yaml.

    Never raises — collects per-entry errors like
    ``study_run_post.run_study_analyses``. Returns ``([], [])`` when there is
    no ``analyses:`` key (the no-op case existing investigations hit today).
    """
    entries = spec.get("analyses") or []
    written: list[str] = []
    errors: list[dict] = []
    for entry in entries:
        try:
            written.extend(_dispatch_analysis(ws_root, inv_slug, entry, study_results))
        except Exception as exc:  # noqa: BLE001 — never crash prepare_investigation
            errors.append({"analysis": entry.get("name"),
                           "error": f"{type(exc).__name__}: {exc}"})
    return written, errors

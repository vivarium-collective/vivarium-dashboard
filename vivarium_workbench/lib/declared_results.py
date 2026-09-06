"""Shared results driver: run declared analyses + viz + report card for a run.

Called by BOTH the study flush (Task 4) and the composite completion seam
(Task 5) so studies and composite runs emit an identical results contract.
``spec`` is any study-shaped dict -- a real ``study.yaml`` or the ephemeral
single-composite spec (``vivarium_workbench.lib.ephemeral_study``) -- read
only for its ``analyses``/``visualizations`` entries.
"""
from __future__ import annotations

import json
from pathlib import Path

from vivarium_workbench.lib.study_run_post import (
    run_study_analyses, render_study_visualizations,
)


def run_declared_results(run_dir, spec: dict, *, ws_root, run_id: str,
                          spec_id: str | None = None) -> dict:
    """Run a run's declared analyses + visualizations + report card.

    Writes ``analyses.json``, ``report.html``, and viz files under
    ``run_dir``. Never raises: every stage is best-effort and any failure is
    captured into the returned ``errors`` list, which also determines
    ``status`` (``"PARTIAL"`` if non-empty, else ``"OK"``).

    An empty spec (no ``analyses`` and no ``visualizations`` declared) is a
    pure no-op: nothing is written to disk.

    Returns ``{"status": "OK"|"PARTIAL", "analyses": <path or None>,
    "report": <path or None>, "viz": [<names>], "errors": [...]}``.
    """
    run_dir = Path(run_dir)
    ws_root = Path(ws_root)
    analyses_entries = list(spec.get("analyses") or [])
    viz_entries = list(spec.get("visualizations") or [])

    if not analyses_entries and not viz_entries:
        return {"status": "OK", "analyses": None, "report": None,
                "viz": [], "errors": []}

    errors: list[dict] = []

    analyses_path = None
    if analyses_entries:
        written, ana_errors = run_study_analyses(run_dir, spec, run_id, ws_root)
        errors.extend(ana_errors)
        try:
            out_path = run_dir / "analyses.json"
            out_path.write_text(
                json.dumps({"written": written, "errors": ana_errors}, default=str),
                encoding="utf-8")
            analyses_path = str(out_path)
        except Exception as exc:  # noqa: BLE001 — best-effort, never raise
            errors.append({"error": f"failed to write analyses.json: "
                                     f"{type(exc).__name__}: {exc}"})

    viz_names: list = []
    if viz_entries:
        viz_files, viz_errors = render_study_visualizations(
            ws_root, run_dir, spec, spec_id)
        viz_names = viz_files
        errors.extend(viz_errors)

    # render_report_card lives in composite_flush.py, which (Task 5) will
    # import run_declared_results from this module -- import lazily here so
    # the two modules never form a load-time cycle.
    from vivarium_workbench.lib.composite_flush import render_report_card

    report_path = None
    try:
        html = render_report_card(req=None, viz_names=viz_names,
                                   analyses=analyses_entries)
        out_path = run_dir / "report.html"
        out_path.write_text(html, encoding="utf-8")
        report_path = str(out_path)
    except Exception as exc:  # noqa: BLE001 — best-effort, never raise
        errors.append({"error": f"failed to render report card: "
                                 f"{type(exc).__name__}: {exc}"})

    status = "PARTIAL" if errors else "OK"
    return {"status": status, "analyses": analyses_path, "report": report_path,
            "viz": viz_names, "errors": errors}

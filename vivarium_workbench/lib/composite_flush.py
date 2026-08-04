"""Generic post-run flush for composite runs: analyses + a report card.

Called by run_runner.execute after visualizations render. Best-effort:
never raises into the run loop; a failure is logged and reflected in the
returned has_* flags."""
from __future__ import annotations

import html as _html
import json
import traceback
from pathlib import Path

from vivarium_workbench.lib.conclusion_card import _CANON_SEVERITY

_RUN_VERDICT_SCHEMA = "run_verdict/v1"


def rollup_run_verdict(verdict_json_paths) -> dict:
    """Roll up a run's report-card ``*.verdict.json`` files into ONE verdict.

    Each path's ``overall`` is canonicalized (unknown / missing / unreadable
    -> ``"ungraded"``); the run's ``overall`` is the WORST (max
    ``_CANON_SEVERITY``) card verdict, ``"ungraded"`` when there are no cards.
    ``cards`` is sorted by name for a stable content hash. Never raises — a
    broken file contributes an ``ungraded`` card, not an exception.

    Returns ``{"schema": "run_verdict/v1", "overall": <canon>,
    "cards": [{"name", "overall"}, ...]}``.
    """
    cards = []
    for p in verdict_json_paths:
        p = Path(p)
        name = p.name[: -len(".verdict.json")] if p.name.endswith(
            ".verdict.json") else p.stem
        overall = "ungraded"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            cand = data.get("overall")
            if cand in _CANON_SEVERITY:
                overall = cand
        except Exception:  # noqa: BLE001 — unreadable/invalid -> ungraded card
            pass
        cards.append({"name": name, "overall": overall})
    cards.sort(key=lambda c: c["name"])
    overall = max(
        (c["overall"] for c in cards),
        key=lambda v: _CANON_SEVERITY.get(v, 0),
        default="ungraded",
    )
    return {"schema": _RUN_VERDICT_SCHEMA, "overall": overall, "cards": cards}


def _composite_analyses(spec_id: str, core) -> list:
    """Return this composite's ``@composite_generator(analyses=[...])``
    declarations (each a dict with at least ``name``, optionally ``params``).
    [] when the generator is unregistered or declares none."""
    try:
        from process_bigraph.composite_generator import _REGISTRY, discover_generators
    except ImportError:
        return []
    if not _REGISTRY:
        discover_generators()
    entry = _REGISTRY.get(spec_id)
    return list(getattr(entry, "analyses", []) or []) if entry else []


def _render_analysis(*, name: str, params: dict, db_file: str, run_id: str,
                      run_dir, core) -> dict:
    """Render one declared analysis over this run's emitter output.

    Reuses the same env-worker ``run_study_analyses`` capability
    ``study_run_post.run_study_analyses`` dispatches to for the study path
    (see env_worker.py's ``_run_study_analyses``), scoped to this run's own
    fixed sweep dir — ``run_dir/parquet/run_id``, the same path
    ``run_runner.execute`` exports as ``VIVARIUM_WORKBENCH_SWEEP_DIR`` and
    ``_render_canonical_viz`` hands ``ParquetAnalysisView`` — and this run's
    ParCa sim_data pickle (``run_runner._resolve_sim_data_path``).

    Raises on failure; the caller (``_dispatch_analyses``) catches per-entry
    so one bad analysis never breaks the flush.
    """
    if run_dir is None:
        raise RuntimeError("run_dir required to resolve this run's sweep dir")
    run_dir = Path(run_dir)
    # run_dir is <ws>/.pbg/runs/<run_id> (see run_runner._resolve_sim_data_path).
    ws_root = run_dir.parents[2]
    sweep_dir = run_dir / "parquet" / run_id

    from vivarium_workbench.lib.run_runner import _resolve_sim_data_path
    sim_data_path = _resolve_sim_data_path(run_dir) or None

    from vivarium_workbench.lib.env_worker_client import EnvWorkerUnavailable
    from vivarium_workbench.lib.env_worker_pool import get_pool
    try:
        res = get_pool().call(ws_root, "run_study_analyses", {
            "entries": [{"name": name, "params": params}],
            "sweep_dir": str(sweep_dir),
            "sim_data_path": sim_data_path,
        })
    except EnvWorkerUnavailable as exc:
        raise RuntimeError(f"environment worker unavailable: {exc}") from exc

    written = list(res.get("written") or [])
    errors = list(res.get("errors") or [])
    if errors and not written:
        raise RuntimeError(f"analysis {name!r} failed: {errors}")
    return {"name": name, "written": written, "errors": errors}


def _dispatch_analyses(*, spec_id: str, db_file: str, run_id: str, core,
                        run_dir=None) -> list:
    """Render every ``@composite_generator(analyses=[...])`` entry over this
    run's emitter output. Returns the list of rendered-artifact dicts; []
    when the composite declares no analyses (graceful no-op). Best-effort:
    each entry is rendered in isolation — a failing analysis is logged and
    skipped, never breaks the flush."""
    analyses = _composite_analyses(spec_id, core)
    if not analyses:
        return []
    out = []
    for a in analyses:
        name = a.get("name") if isinstance(a, dict) else str(a)
        params = (a.get("params") or {}) if isinstance(a, dict) else {}
        try:
            rendered = _render_analysis(
                name=name, params=params, db_file=db_file, run_id=run_id,
                run_dir=run_dir, core=core)
        except Exception:
            traceback.print_exc()
            continue
        if rendered:
            out.append(rendered)
    return out


def render_report_card(*, req, viz_names: list, analyses: list) -> str:
    steps = getattr(req, "steps", "?")
    spec_id = getattr(req, "spec_id", "") or ""
    name = spec_id.rsplit(".", 1)[-1] if spec_id else "composite"
    rows = "".join(
        f"<li><code>{_html.escape(str(n))}</code></li>" for n in viz_names
    ) or "<li><em>none</em></li>"
    an = "".join(
        f"<li>{_html.escape(str(a.get('name', a)))}</li>" for a in analyses
    ) or "<li><em>none</em></li>"
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<div style='font-family:system-ui;max-width:720px;margin:24px auto'>"
        f"<h2>Run report — <code>{_html.escape(name)}</code></h2>"
        f"<p><strong>Composite:</strong> <code>{_html.escape(spec_id)}</code><br>"
        f"<strong>Steps:</strong> {_html.escape(str(steps))}</p>"
        f"<h3>Figures ({len(viz_names)})</h3><ul>{rows}</ul>"
        f"<h3>Analyses ({len(analyses)})</h3><ul>{an}</ul>"
        "</div>"
    )


def run_flush(run_dir: Path, *, req, spec_id: str, db_file: str,
              run_id: str, core) -> dict:
    run_dir = Path(run_dir)
    analyses: list = []
    has_analyses = False
    try:
        analyses = _dispatch_analyses(
            spec_id=spec_id, db_file=db_file, run_id=run_id, core=core,
            run_dir=run_dir)
        has_analyses = bool(analyses)
    except Exception:
        traceback.print_exc()
    try:
        (run_dir / "analyses.json").write_text(
            json.dumps(analyses, default=str), encoding="utf-8")
    except Exception:
        traceback.print_exc()

    # Report card — always attempt; read viz names from the already-written viz.json.
    viz_names: list = []
    try:
        vj = run_dir / "viz.json"
        if vj.is_file():
            viz_names = list(json.loads(vj.read_text()).keys())
    except Exception:
        pass
    has_report = False
    try:
        (run_dir / "report.html").write_text(
            render_report_card(req=req, viz_names=viz_names, analyses=analyses),
            encoding="utf-8")
        has_report = True
    except Exception:
        traceback.print_exc()

    # Computed verdict (Phase 2c): roll up the report-card *.verdict.json files
    # this run's analyses just wrote into ONE run_dir/verdict.json artifact.
    # Best-effort — a verdict error never fails the run.
    has_verdict = False
    try:
        vpaths = [Path(w) for a in analyses
                  for w in (a.get("written") or [])
                  if str(w).endswith(".verdict.json")]
        (run_dir / "verdict.json").write_text(
            json.dumps(rollup_run_verdict(vpaths)), encoding="utf-8")
        has_verdict = True
    except Exception:
        traceback.print_exc()
    return {"has_analyses": has_analyses, "has_report": has_report,
            "has_verdict": has_verdict}

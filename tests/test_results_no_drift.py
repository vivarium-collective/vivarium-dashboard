"""No-drift guard (Task 4, descoped).

Task 4's brief wanted ``_run_post_run_flush`` (study_runs.py) refactored to
CALL the shared ``run_declared_results`` driver. The controller descoped
that: ``_run_post_run_flush`` is entangled with a ``skip_analyses`` gate,
run-dir viz.json mirroring, static-image handling, and a strict 8-stage
order (see its docstring, study_runs.py:135) -- routing it through the
driver risked regressing a working path for marginal benefit.

"No drift" is instead ALREADY structurally satisfied: both the composite
path (``declared_results.run_declared_results``) and the study path
(``study_runs._run_post_run_flush``) source their analyses via the SAME
primitive, ``study_run_post.run_study_analyses`` -- they just call it from
two different call sites rather than one shared one.

This test enforces that invariant so it can't silently rot: if a future
edit makes either path stop calling ``study_run_post.run_study_analyses``
(e.g. inlines its own dispatch, or calls a different helper), the
corresponding assertion below fails.
"""
from pathlib import Path

import yaml
import pytest

from vivarium_workbench.lib import (
    composite_subprocess,
    declared_results,
    study_run_post,
    study_run_state,
    study_runs,
)


def test_both_paths_import_the_same_function_object():
    """Sanity check: ``declared_results`` imported ``run_study_analyses`` BY
    REFERENCE from ``study_run_post`` -- not a look-alike of its own. If a
    future edit swaps in a different (even similarly-named) helper, this
    identity check catches it even before any call-tracing test would."""
    assert declared_results.run_study_analyses is study_run_post.run_study_analyses


def test_composite_path_calls_shared_run_study_analyses(tmp_path, monkeypatch):
    """``run_declared_results`` (the composite/Task-5 path) must dispatch
    analyses through ``study_run_post.run_study_analyses`` (bound into
    ``declared_results`` at import time)."""
    calls = []

    def spy(study_dir, spec, run_id, ws_root):
        calls.append((study_dir, spec, run_id, ws_root))
        return ([], [])

    monkeypatch.setattr(declared_results, "run_study_analyses", spy)
    monkeypatch.setattr(declared_results, "render_study_visualizations",
                         lambda *a, **k: ([], []))

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spec = {"analyses": [{"name": "some_analysis"}], "visualizations": []}

    declared_results.run_declared_results(
        run_dir, spec, ws_root=tmp_path, run_id="r1")

    assert len(calls) == 1
    assert calls[0][0] == run_dir
    assert calls[0][2] == "r1"


# ---------------------------------------------------------------------------
# Study-flush harness (mirrors tests/test_study_runs_lib.py's hermetic_engine,
# but leaves run_study_analyses as a SPY instead of a no-op -- we want to
# prove _run_post_run_flush actually calls it, not just neutralise it).
# ---------------------------------------------------------------------------

def _write_workspace(ws: Path, package_path: str = "demo_pkg") -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "workspace.yaml").write_text(
        f'schema_version: 2\nname: demo\ncreated: "2026-06-26"\n'
        f'package_path: {package_path}\n',
        encoding="utf-8",
    )


def _write_study(ws: Path, name: str, baseline: list) -> Path:
    sd = ws / "studies" / name
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3, "name": name, "created": "2026-06-26",
        "status": "planned", "objective": "",
        "baseline": baseline,
        "variants": [],
        "runs": [], "visualizations": [], "comparisons": [],
        "conclusion": None, "parent_studies": [], "interventions": [],
    }), encoding="utf-8")
    return sd


@pytest.fixture
def hermetic_study_flush(monkeypatch):
    """Neutralise the run-dispatch seams (subprocess + baseline-state
    resolver) and the unrelated flush stages (viz + post-run scripts) so
    ``run_study_baseline`` completes end to end with no real simulation --
    but leave ``study_run_post.run_study_analyses`` as a SPY so we can
    assert ``_run_post_run_flush`` actually calls it."""
    calls: dict = {"analyses": []}

    def fake_run(ws_root, **kw):
        return ({"simulation_id": "run-x", "status": "completed"}, 200)

    def fake_resolve(ws_root, pkg, spec_id, params):
        return ({}, None)

    def spy_analyses(study_dir, spec, run_id, ws_root):
        calls["analyses"].append((study_dir, spec, run_id, ws_root))
        return ([], [])

    monkeypatch.setattr(composite_subprocess, "run_composite_subprocess", fake_run)
    monkeypatch.setattr(study_run_state, "resolve_study_baseline_state", fake_resolve)
    monkeypatch.setattr(study_run_post, "render_study_visualizations",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(study_run_post, "run_post_run_scripts",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(study_run_post, "run_study_analyses", spy_analyses)
    return calls


def test_study_path_calls_shared_run_study_analyses(tmp_path, hermetic_study_flush):
    """``_run_post_run_flush`` (the study path) must dispatch analyses
    through ``study_run_post.run_study_analyses`` -- looked up as a module
    attribute at call time, so patching it here is exactly what a real
    caller sees."""
    ws = tmp_path / "ws"
    _write_workspace(ws)
    _write_study(ws, "s1", [
        {"name": "core", "composite": "demo_pkg.composites.cell",
         "params": {"k": 2, "n_steps": 7}},
    ])

    resp, code = study_runs.run_study_baseline(ws, {"study": "s1"})

    assert code == 200, resp
    assert len(hermetic_study_flush["analyses"]) == 1


def test_study_path_skip_analyses_does_not_call_it(tmp_path, hermetic_study_flush):
    """Converse check: the ``skip_analyses`` gate (env_worker's own
    analysis dispatch) must still suppress the call -- proving the spy
    above is actually wired to the real conditional, not a tautology that
    fires regardless of the flush's own logic."""
    ws = tmp_path / "ws"
    _write_workspace(ws)
    _write_study(ws, "s1", [
        {"name": "core", "composite": "demo_pkg.composites.cell",
         "params": {"k": 2, "n_steps": 7}},
    ])

    resp, code = study_runs.run_study_baseline(
        ws, {"study": "s1", "skip_analyses": True})

    assert code == 200, resp
    assert hermetic_study_flush["analyses"] == []

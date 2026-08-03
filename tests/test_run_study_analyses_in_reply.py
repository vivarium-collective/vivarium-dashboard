"""``env_worker._run_study`` invokes a study's declared ``analyses:`` directly
and folds their output into its reply (store data-flow refactor, Task 1;
docs/superpowers/specs/2026-08-02-store-dataflow-refactor-design.md §1).

Hermetic, mirroring ``tests/test_run_study_capability.py`` (fake
``study_runs.run_study_baseline`` writing a fake ``runs.db`` row) and
``tests/test_investigation_analysis_step.py`` (a fake ``v2ecoli.workflow.analysis``
module injected via ``sys.modules`` so no real v2ecoli Analysis stack is
needed).

Two things are under test:
  1. ``_run_study``'s reply carries ``analyses[name]`` (incl. ``"verdict"``),
     and the analysis was constructed with ``study_dir``/``runs_db`` in its
     config — the whole point (a config study's comparison verdict flows
     back in the reply instead of via disk).
  2. The "avoid the double-run" guarantee: the parquet post-flush's
     ``study_run_post.run_study_analyses`` (stage 3 of
     ``study_runs._run_post_run_flush``) is skipped when ``skip_analyses``
     is threaded True — asserted directly against ``_run_post_run_flush``
     (the seam ``_run_study`` sets), independent of the heavier
     baseline-launch machinery.
"""
from __future__ import annotations

import sqlite3
import sys
import types

from vivarium_workbench import env_worker
from vivarium_workbench.lib import study_runs


def _install_fake_registry(registry: dict) -> None:
    """Inject a fake ``v2ecoli.workflow.analysis`` module so
    ``from v2ecoli.workflow.analysis import ANALYSIS_REGISTRY`` resolves to
    ``registry`` without needing the real v2ecoli Analysis stack."""
    fake_mod = types.ModuleType("v2ecoli.workflow.analysis")
    fake_mod.ANALYSIS_REGISTRY = registry  # type: ignore[attr-defined]
    sys.modules["v2ecoli.workflow.analysis"] = fake_mod


def _write_runs_meta_row(db_file, *, run_id, spec_id="pkg.composites.demo",
                         label="baseline", sim_name="baseline",
                         status="completed"):
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS runs_meta ("
        "run_id TEXT PRIMARY KEY, spec_id TEXT, label TEXT, sim_name TEXT, "
        "status TEXT, started_at REAL, completed_at REAL, n_steps INTEGER)"
    )
    conn.execute(
        "INSERT INTO runs_meta (run_id, spec_id, label, sim_name, status, "
        "started_at, completed_at, n_steps) VALUES (?,?,?,?,?,?,?,?)",
        (run_id, spec_id, label, sim_name, status, 1.0, 2.0, 5),
    )
    conn.commit()
    conn.close()


def _study_dir_with_analyses(workspace, slug="demo"):
    d = workspace / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.yaml").write_text(
        f"name: {slug}\n"
        "baseline: [{name: core, composite: pkg.x}]\n"
        "analyses:\n"
        "  - name: fake_cmp\n"
        "    params:\n"
        "      candidate_run: demo\n"
        "      reference_run: reference\n"
    )
    return d


class _FakeCmpAnalysis:
    """Mimics a real comparison analysis (e.g. comparison_cards): captures the
    config it was constructed with and returns a verdict-shaped output."""

    calls: list = []

    def __init__(self, config, core=None):
        self.config = config
        self.core = core
        _FakeCmpAnalysis.calls.append(config)

    def update(self):
        return {"verdict": {"overall": "within_tol"}, "cards": {}}


# ---------------------------------------------------------------------------
# 1. _run_study reply carries the analysis verdict + context
# ---------------------------------------------------------------------------

def test_run_study_reply_carries_analysis_verdict(tmp_path, monkeypatch):
    _FakeCmpAnalysis.calls = []
    _install_fake_registry({"fake_cmp": _FakeCmpAnalysis})

    workspace = tmp_path / "ws"
    sd = _study_dir_with_analyses(workspace)
    db_file = sd / "runs.db"

    seen_bodies = []

    def fake_run_study_baseline(ws_root, body):
        seen_bodies.append(body)
        run_id = "run-baseline-1"
        _write_runs_meta_row(db_file, run_id=run_id)
        return {"simulation_id": run_id, "results": {}}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)

    result = env_worker._run_study({"workspace": str(workspace), "study_slug": "demo"})

    # run_refs/verdict/errors still present, unchanged shape.
    assert result["errors"] == []
    assert "run_refs" in result and len(result["run_refs"]) == 1
    assert "verdict" in result  # None here — no conclusion card written by the fake

    # analyses: additive key, holds the fake analysis's verdict-shaped output.
    assert result["analyses"]["fake_cmp"]["verdict"] == {"overall": "within_tol"}
    assert result["analyses"]["fake_cmp"]["cards"] == {}

    # The analysis was constructed with study_dir + runs_db in its config —
    # the whole point: it gets its context by construction, not discovery.
    assert len(_FakeCmpAnalysis.calls) == 1
    cfg = _FakeCmpAnalysis.calls[0]
    assert cfg["study_dir"] == str(sd)
    assert cfg["runs_db"] == str(db_file)
    assert cfg["candidate_run"] == "demo"
    assert cfg["reference_run"] == "reference"

    # skip_analyses=True was threaded to run_study_baseline's body, so the
    # parquet post-flush (which the fake never actually reaches) would have
    # skipped stage 3 had it run.
    assert seen_bodies[0].get("skip_analyses") is True


def test_run_study_no_analyses_declared_omits_analyses_key(tmp_path, monkeypatch):
    # Backward-compat: a study with no analyses: must not gain the key (the
    # existing test_run_study_capability.py fixtures assert an exact
    # {run_refs, verdict, errors} key set).
    workspace = tmp_path / "ws"
    sd = workspace / "studies" / "demo"
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text("name: demo\nbaseline: [{name: core, composite: pkg.x}]\n")
    db_file = sd / "runs.db"

    def fake_run_study_baseline(ws_root, body):
        _write_runs_meta_row(db_file, run_id="run-1")
        return {"simulation_id": "run-1"}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)

    result = env_worker._run_study({"workspace": str(workspace), "study_slug": "demo"})

    assert result["errors"] == []
    assert "analyses" not in result


def test_run_study_unknown_analysis_records_error_not_raise(tmp_path, monkeypatch):
    _install_fake_registry({})  # fake_cmp not registered

    workspace = tmp_path / "ws"
    sd = _study_dir_with_analyses(workspace)
    db_file = sd / "runs.db"

    def fake_run_study_baseline(ws_root, body):
        _write_runs_meta_row(db_file, run_id="run-1")
        return {"simulation_id": "run-1"}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)

    result = env_worker._run_study({"workspace": str(workspace), "study_slug": "demo"})

    assert result["analyses"] == {}
    assert len(result["errors"]) == 1
    assert result["errors"][0]["analysis"] == "fake_cmp"
    assert "fake_cmp" in result["errors"][0]["error"]


def test_run_study_raising_analysis_records_error_not_raise(tmp_path, monkeypatch):
    class _RaisingAnalysis:
        def __init__(self, config, core=None):
            pass

        def update(self):
            raise RuntimeError("comparison blew up")

    _install_fake_registry({"fake_cmp": _RaisingAnalysis})

    workspace = tmp_path / "ws"
    sd = _study_dir_with_analyses(workspace)
    db_file = sd / "runs.db"

    def fake_run_study_baseline(ws_root, body):
        _write_runs_meta_row(db_file, run_id="run-1")
        return {"simulation_id": "run-1"}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)

    result = env_worker._run_study({"workspace": str(workspace), "study_slug": "demo"})

    assert result["analyses"] == {}
    assert len(result["errors"]) == 1
    assert result["errors"][0]["analysis"] == "fake_cmp"
    assert "comparison blew up" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# 2. Avoid the double-run: skip_analyses threads to the parquet post-flush
# ---------------------------------------------------------------------------

def test_run_post_run_flush_skips_analyses_stage_when_flagged(tmp_path, monkeypatch):
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)

    monkeypatch.setattr(study_runs.study_run_post, "render_study_visualizations",
                        lambda *a, **k: ([], []))
    monkeypatch.setattr(study_runs.study_run_post, "run_post_run_scripts",
                        lambda *a, **k: ([], []))

    calls = []

    def spy_run_study_analyses(*a, **k):
        calls.append((a, k))
        return ([], [])

    monkeypatch.setattr(study_runs.study_run_post, "run_study_analyses",
                        spy_run_study_analyses)

    study_runs._run_post_run_flush(
        tmp_path, study_dir, {}, "spec.id", "run-1", {}, {}, {},
        skip_analyses=True,
    )
    assert calls == [], "run_study_analyses must NOT be invoked when skip_analyses=True"

    study_runs._run_post_run_flush(
        tmp_path, study_dir, {}, "spec.id", "run-1", {}, {}, {},
        skip_analyses=False,
    )
    assert len(calls) == 1, "run_study_analyses must still run for every other caller"


def test_run_study_baseline_threads_skip_analyses_to_launch(tmp_path, monkeypatch):
    # run_study_baseline pops skip_analyses off the body and forwards it to
    # launch_into_study (which forwards to _launch_run_and_flush →
    # _run_post_run_flush).
    (tmp_path / "studies" / "s1").mkdir(parents=True)
    (tmp_path / "studies" / "s1" / "study.yaml").write_text(
        "name: s1\nbaseline: [{name: core, composite: pkg.x}]\n")

    seen = {}

    def fake_launch_into_study(ws_root, study, spec_id, params, n_steps, **kwargs):
        seen.update(kwargs)
        return {"simulation_id": "r1"}, 200

    monkeypatch.setattr(study_runs, "launch_into_study", fake_launch_into_study)

    study_runs.run_study_baseline(tmp_path, {"study": "s1", "skip_analyses": True})
    assert seen.get("skip_analyses") is True

    study_runs.run_study_baseline(tmp_path, {"study": "s1"})
    assert seen.get("skip_analyses") is False

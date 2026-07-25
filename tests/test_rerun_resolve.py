# tests/test_rerun_resolve.py
from pathlib import Path
from vivarium_workbench.lib import rerun, composite_runs as cr

def _seed(db_path, run_id, spec_id, params, n_steps, status="completed"):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = cr.connect(db_path)
    import json
    conn.execute("INSERT INTO runs_meta (run_id, spec_id, params_json, started_at, status, n_steps) "
                 "VALUES (?,?,?,?,?,?)", (run_id, spec_id, json.dumps(params), 0.0, status, n_steps))
    conn.commit(); conn.close()

def test_study_origin(tmp_path):
    # a run in studies/<slug>/runs.db → origin study, slug from dir
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    study_dir = tmp_path / "workspace" / "studies" / "s1"
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / "study.yaml").write_text("name: s1\n")
    db = study_dir / "runs.db"
    _seed(db, "spec__1__a", "v2ecoli.composites.baseline.baseline", {"seed": 0}, 100)
    t = rerun.resolve_rerun_target(tmp_path, "spec__1__a")
    assert t["origin"] == "study" and t["study"] == "s1"
    assert t["spec_id"] == "v2ecoli.composites.baseline.baseline"
    assert t["params"] == {"seed": 0} and t["n_steps"] == 100

def test_composite_origin(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed(db, "spec__2__b", "some.composite", {"x": 1}, 5)
    t = rerun.resolve_rerun_target(tmp_path, "spec__2__b")
    assert t["origin"] == "composite" and t["study"] is None

def test_not_found(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    assert rerun.resolve_rerun_target(tmp_path, "nope") is None

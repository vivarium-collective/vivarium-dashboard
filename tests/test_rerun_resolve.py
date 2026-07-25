# tests/test_rerun_resolve.py
import json
from pathlib import Path
from vivarium_workbench.lib import rerun, composite_runs as cr

def _seed(db_path, run_id, spec_id, params, n_steps, status="completed", manifest=None):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = cr.connect(db_path)
    conn.execute(
        "INSERT INTO runs_meta (run_id, spec_id, params_json, started_at, status, n_steps, manifest_json) "
        "VALUES (?,?,?,?,?,?,?)",
        (run_id, spec_id, json.dumps(params), 0.0, status, n_steps,
         json.dumps(manifest) if manifest else None))
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


def test_legacy_no_manifest_falls_back(tmp_path):
    # A row with only params_json + n_steps (no manifest) — legacy fallback,
    # emitter/emit_paths/runtime absent (None) for a uniform shape.
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed(db, "spec__3__c", "some.composite", {"x": 1}, 5)
    t = rerun.resolve_rerun_target(tmp_path, "spec__3__c")
    assert t["spec_id"] == "some.composite"
    assert t["params"] == {"x": 1} and t["n_steps"] == 5
    assert t["emitter"] is None and t["emit_paths"] is None and t["runtime"] is None


def test_manifest_present_preferred(tmp_path):
    # A row WITH a full manifest_json — resolve_rerun_target prefers it over
    # the delta params_json/n_steps, and returns emitter/emit_paths/runtime.
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    study_dir = tmp_path / "workspace" / "studies" / "s1"
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / "study.yaml").write_text("name: s1\n")
    db = study_dir / "runs.db"
    manifest = {
        "version": 1, "spec_id": "v2ecoli.composites.baseline.baseline",
        "params": {"seed": 0, "cache_dir": "out/cache"}, "n_steps": 200,
        "emitter": "parquet", "emit_paths": ["bulk", "listeners"],
        "runtime": {"subprocess_timeout_s": 1800, "emitter": "parquet"},
        "origin": "study", "study": "s1", "pkg": "v2ecoli",
    }
    # Delta params_json/n_steps deliberately differ from the manifest to prove
    # the manifest wins.
    _seed(db, "spec__4__d", "v2ecoli.composites.baseline.baseline",
         {"seed": 0}, 100, manifest=manifest)
    t = rerun.resolve_rerun_target(tmp_path, "spec__4__d")
    assert t["origin"] == "study" and t["study"] == "s1"
    assert t["spec_id"] == "v2ecoli.composites.baseline.baseline"
    assert t["params"] == {"seed": 0, "cache_dir": "out/cache"}
    assert t["n_steps"] == 200
    assert t["emitter"] == "parquet"
    assert t["emit_paths"] == ["bulk", "listeners"]
    assert t["runtime"] == {"subprocess_timeout_s": 1800, "emitter": "parquet"}

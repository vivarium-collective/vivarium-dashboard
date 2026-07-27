from vivarium_workbench.lib import rerun


def test_run_rerun_study_forwards_full_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: {
        "run_id": rid, "origin": "study", "study": "s1", "spec_id": "c",
        "params": {"seed": 2, "cache_dir": "out/cache"}, "n_steps": 80,
        "emitter": "parquet", "emit_paths": ["bulk"], "runtime": {"emitter": "parquet"},
        "seed": 2})
    seen = {}
    monkeypatch.setattr(rerun.study_runs, "launch_into_study",
        lambda ws, study, spec_id, params, n_steps, **k: seen.update(
            study=study, spec_id=spec_id, params=params, n_steps=n_steps, kw=k)
            or ({"run_id": "r2", "status": "running"}, 200))
    resp, status = rerun.run_rerun(tmp_path, "r1")
    assert resp["run_id"] == "r2" and resp["origin"] == "study" and resp["reran"] == "r1"
    assert seen["spec_id"] == "c" and seen["params"]["cache_dir"] == "out/cache"
    assert seen["kw"]["emitter"] == "parquet" and seen["kw"]["emit_paths"] == ["bulk"]
    assert seen["kw"]["runtime"] == {"emitter": "parquet"}
    # reproducible-rerun-spine Task 4: the ORIGINAL run's first-class seed and
    # reran_from=<original run_id> are forwarded so the new run's manifest
    # carries the same seed and its completion can be verified against r1.
    assert seen["kw"]["seed"] == 2
    assert seen["kw"]["reran_from"] == "r1"


def test_run_rerun_composite(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: {
        "run_id": rid, "origin": "composite", "study": None, "spec_id": "c.comp",
        "params": {"x": 1}, "n_steps": 5, "emitter": None, "emit_paths": ["bulk"], "runtime": None})
    seen = {}
    monkeypatch.setattr(rerun.cli_runs, "run_composite",
        lambda ws, spec_id, *, steps, params, emit_paths, detach: seen.update(
            spec_id=spec_id, params=params, emit_paths=emit_paths, detach=detach)
            or ({"run_id": "r3", "status": "running"}, 202))
    resp, status = rerun.run_rerun(tmp_path, "r1")
    assert resp["run_id"] == "r3" and seen["detach"] is True and seen["emit_paths"] == ["bulk"]


def test_run_rerun_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "resolve_rerun_target", lambda ws, rid: None)
    assert rerun.run_rerun(tmp_path, "x")[1] == 404


def test_rerun_investigation(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun, "_investigation_studies", lambda ws, inv: ["s1", "s2"])
    launched = []
    monkeypatch.setattr(rerun.study_runs, "run_study_baseline",
        lambda ws, body: launched.append(body["study"]) or ({"run_id": "r-"+body["study"], "status": "running"}, 200))
    resp, _ = rerun.rerun_investigation(tmp_path, "inv1")
    assert launched == ["s1", "s2"] and resp["count"] == 2

"""launch_into_study — explicit replay inputs + manifest stamping (Task 3).

Hermetic: stubs run_core.invoke_run and the internal _launch_run_and_flush
seam so no real subprocess/flush runs; asserts launch_into_study resolves the
study's own runs.db, forwards the explicit spec_id/params/n_steps to
invoke_run, and builds + forwards a manifest carrying emitter/emit_paths/
runtime through to the (stubbed) launch+flush helper.
"""
from vivarium_workbench.lib import study_runs


def test_launch_into_study_explicit_inputs_and_manifest(tmp_path, monkeypatch):
    # A study dir must already exist for _resolve_study_dir's flat fallback
    # to resolve to studies/<name> (it falls back to investigations/<name>
    # when neither exists).
    (tmp_path / "studies" / "s1").mkdir(parents=True)

    seen = {}

    def fake_invoke_run(ws_root, *, spec_id, config, db_path, label, n_steps):
        seen.update(spec_id=spec_id, config=config, db_path=db_path, n_steps=n_steps)
        class P:
            pass
        return P()

    monkeypatch.setattr(study_runs.run_core, "invoke_run", fake_invoke_run)

    manifests = []
    monkeypatch.setattr(
        study_runs, "_launch_run_and_flush",
        lambda *a, **k: (manifests.append(k.get("manifest")) or
                         ({"run_id": "r-new", "status": "running"}, 200)),
        raising=False,
    )

    resp, status = study_runs.launch_into_study(
        tmp_path, "s1", "some.composite", {"seed": 3}, 50,
        emitter="parquet", emit_paths=["bulk"], runtime={"emitter": "parquet"})

    assert "studies/s1/runs.db" in seen["db_path"].replace("\\", "/")
    assert seen["spec_id"] == "some.composite" and seen["config"].get("seed") == 3
    assert status == 200 and resp["run_id"]
    m = manifests[-1]
    assert m and m["emitter"] == "parquet" and m["emit_paths"] == ["bulk"]
    assert m["spec_id"] == "some.composite" and m["params"].get("seed") == 3
    assert m["origin"] == "study" and m["study"] == "s1"


def test_launch_into_study_remote_build_guard_409(tmp_path, monkeypatch):
    """A remote-build workspace (.viv-build.json) rejects before any flush —
    mirrors run_study_baseline's existing 409 guard."""
    (tmp_path / "studies" / "s1").mkdir(parents=True)
    (tmp_path / ".viv-build.json").write_text("{}")

    called = []
    monkeypatch.setattr(
        study_runs, "_launch_run_and_flush",
        lambda *a, **k: called.append(1) or ({}, 200),
        raising=False,
    )

    resp, status = study_runs.launch_into_study(
        tmp_path, "s1", "some.composite", {}, 5)
    assert status == 409
    assert not called

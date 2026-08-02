"""``env_worker._run_study`` — the persistent worker's ``run_study`` capability
(investigation-as-composite design, §Architecture 2). Hermetic: monkeypatches
``vivarium_workbench.lib.study_runs.run_study_baseline`` / ``run_study_variant``
to fakes that write a fake ``runs.db`` row (mirroring what the real launch +
post-run flush would do), and asserts ``_run_study`` returns the
``{run_refs, verdict, errors}`` shape — recording failures in ``errors``
instead of raising.
"""
from __future__ import annotations

import json
import sqlite3

from vivarium_workbench import env_worker
from vivarium_workbench.lib import study_runs


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


def _study_dir(workspace, slug="demo"):
    d = workspace / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.yaml").write_text(f"name: {slug}\nbaseline: [{{name: core, composite: pkg.x}}]\n")
    return d


# ---------------------------------------------------------------------------
# Contract shape + happy path
# ---------------------------------------------------------------------------

def test_run_study_baseline_only_returns_run_refs_and_no_errors(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    sd = _study_dir(workspace)
    db_file = sd / "runs.db"

    def fake_run_study_baseline(ws_root, body):
        assert body == {"study": "demo"}
        run_id = "run-baseline-1"
        _write_runs_meta_row(db_file, run_id=run_id)
        return {"simulation_id": run_id, "results": {}}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)

    result = env_worker._run_study({"workspace": str(workspace), "study_slug": "demo"})

    assert set(result.keys()) == {"run_refs", "verdict", "errors"}
    assert result["errors"] == []
    assert result["verdict"] is None  # no conclusion card written by the fake
    assert len(result["run_refs"]) == 1
    assert result["run_refs"][0]["run_id"] == "run-baseline-1"
    assert result["run_refs"][0]["status"] == "completed"


def test_run_study_baseline_plus_named_variants(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    sd = _study_dir(workspace)
    db_file = sd / "runs.db"

    def fake_run_study_baseline(ws_root, body):
        _write_runs_meta_row(db_file, run_id="run-baseline", sim_name="baseline")
        return {"simulation_id": "run-baseline"}, 200

    def fake_run_study_variant(ws_root, body):
        assert body["study"] == "demo"
        variant = body["variant"]
        run_id = f"run-{variant}"
        _write_runs_meta_row(db_file, run_id=run_id, sim_name=variant)
        return {"simulation_id": run_id}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)
    monkeypatch.setattr(study_runs, "run_study_variant", fake_run_study_variant)

    result = env_worker._run_study({
        "workspace": str(workspace),
        "study_slug": "demo",
        "run_spec": {"variants": ["fast", "slow"]},
    })

    assert result["errors"] == []
    run_ids = [r["run_id"] for r in result["run_refs"]]
    assert run_ids == ["run-baseline", "run-fast", "run-slow"]


def test_run_study_reads_conclusion_verdict_when_present(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    sd = _study_dir(workspace)
    db_file = sd / "runs.db"
    verdict_dir = sd / "viz" / "report_card"
    verdict_dir.mkdir(parents=True)
    verdict_payload = {"schema": "conclusion_card/v1", "overall": "within_tol"}
    (verdict_dir / "conclusion.verdict.json").write_text(json.dumps(verdict_payload))

    def fake_run_study_baseline(ws_root, body):
        _write_runs_meta_row(db_file, run_id="run-1")
        return {"simulation_id": "run-1"}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)

    result = env_worker._run_study({"workspace": str(workspace), "study_slug": "demo"})

    assert result["errors"] == []
    assert result["verdict"] == verdict_payload


# ---------------------------------------------------------------------------
# Never raises — failures land in errors
# ---------------------------------------------------------------------------

def test_missing_workspace_records_error_not_raise():
    result = env_worker._run_study({"study_slug": "demo"})
    assert result["run_refs"] == []
    assert result["verdict"] is None
    assert len(result["errors"]) == 1
    assert "workspace" in result["errors"][0]["error"]


def test_missing_study_slug_records_error_not_raise(tmp_path):
    result = env_worker._run_study({"workspace": str(tmp_path)})
    assert result["run_refs"] == []
    assert len(result["errors"]) == 1
    assert "study_slug" in result["errors"][0]["error"]


def test_baseline_exception_is_captured_not_raised(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    _study_dir(workspace)

    def fake_run_study_baseline(ws_root, body):
        raise RuntimeError("boom")

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)

    result = env_worker._run_study({"workspace": str(workspace), "study_slug": "demo"})

    assert result["run_refs"] == []
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "baseline"
    assert "boom" in result["errors"][0]["error"]


def test_baseline_non_200_records_error_and_continues_to_variants(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    sd = _study_dir(workspace)
    db_file = sd / "runs.db"

    def fake_run_study_baseline(ws_root, body):
        return {"error": "study has no baseline composites"}, 400

    def fake_run_study_variant(ws_root, body):
        _write_runs_meta_row(db_file, run_id="run-only-variant", sim_name="v1")
        return {"simulation_id": "run-only-variant"}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)
    monkeypatch.setattr(study_runs, "run_study_variant", fake_run_study_variant)

    result = env_worker._run_study({
        "workspace": str(workspace),
        "study_slug": "demo",
        "run_spec": {"variants": ["v1"]},
    })

    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "baseline"
    assert result["errors"][0]["status"] == 400
    # the variant still ran and its run ref is still harvested
    assert [r["run_id"] for r in result["run_refs"]] == ["run-only-variant"]


def test_variant_exception_does_not_block_other_variants(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    sd = _study_dir(workspace)
    db_file = sd / "runs.db"

    def fake_run_study_baseline(ws_root, body):
        _write_runs_meta_row(db_file, run_id="run-baseline")
        return {"simulation_id": "run-baseline"}, 200

    def fake_run_study_variant(ws_root, body):
        if body["variant"] == "boom":
            raise RuntimeError("variant blew up")
        _write_runs_meta_row(db_file, run_id="run-ok", sim_name="ok")
        return {"simulation_id": "run-ok"}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)
    monkeypatch.setattr(study_runs, "run_study_variant", fake_run_study_variant)

    result = env_worker._run_study({
        "workspace": str(workspace),
        "study_slug": "demo",
        "run_spec": {"variants": ["boom", "ok"]},
    })

    stages = [e["stage"] for e in result["errors"]]
    assert stages == ["variant:boom"]
    run_ids = [r["run_id"] for r in result["run_refs"]]
    assert run_ids == ["run-baseline", "run-ok"]


def test_unresolvable_study_dir_records_error_but_does_not_raise(tmp_path, monkeypatch):
    """No study.yaml AND no studies/<slug> dir at all — _resolve_study_dir's
    flat fallback still returns investigations/<slug> (never raises itself),
    so exercise the harvest-skip path via a runs.db that simply never gets
    written (the launch mock reports a run_id, but the file doesn't exist)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    def fake_run_study_baseline(ws_root, body):
        return {"simulation_id": "run-ghost"}, 200

    monkeypatch.setattr(study_runs, "run_study_baseline", fake_run_study_baseline)

    result = env_worker._run_study({"workspace": str(workspace), "study_slug": "ghost"})

    # No exception; the run_id was reported but runs.db never existed, so no
    # run_ref is fabricated and no spurious error either (db_file.is_file() gates it).
    assert result["run_refs"] == []
    assert result["errors"] == []

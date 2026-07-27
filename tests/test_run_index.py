# tests/test_run_index.py
"""find_matching_run — retrieve-before-recompute lookup (reproducible-
rerun-spine Task 6 / G5). Unit-level: seeds runs_meta rows directly (same
convention as test_rerun.py's ``_seed_run``) rather than driving a full
composite run, since the function under test is a pure DB + filesystem
read."""
import json

from vivarium_workbench.lib import composite_runs as cr
from vivarium_workbench.lib import result_fingerprint as rfp
from vivarium_workbench.lib import run_index
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _seed_run(db_path, run_id, *, spec_id="s", params=None, manifest=None,
              env_id=None, result_fingerprint=None, status="completed"):
    """Insert a runs_meta row with the fields find_matching_run reads.
    Mirrors test_rerun.py's ``_seed_run`` but also accepts an optional
    ``manifest`` dict (stored as manifest_json) so config/seed can be
    exercised via the manifest-preferred path."""
    conn = cr.connect(db_path)
    conn.execute(
        "INSERT INTO runs_meta (run_id, spec_id, params_json, started_at, status, n_steps) "
        "VALUES (?,?,?,?,?,?)",
        (run_id, spec_id, json.dumps(params or {}), 0.0, status, 1),
    )
    conn.commit()
    conn.execute(
        "UPDATE runs_meta SET env_id=?, result_fingerprint=?, manifest_json=? "
        "WHERE run_id=?",
        (env_id, result_fingerprint,
         json.dumps(manifest) if manifest is not None else None, run_id),
    )
    conn.commit()
    conn.close()


def _make_artifact(ws_root, run_id):
    """Simulate an intact saved run: write the canonical output snapshot a
    real run's completion tail would have written (result_fingerprint.
    write_snapshot), so _artifact_intact sees a real file on disk."""
    wp = WorkspacePaths.load(ws_root)
    run_dir = wp.pbg / "runs" / run_id
    rfp.write_snapshot(run_dir, {}, [])


def _ws(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    return tmp_path


def test_find_matching_run_hit(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a", params={"X": 1, "seed": 7},
              manifest={"params": {"X": 1, "seed": 7, "n_steps": 5}, "seed": 7},
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(ws, "spec.a", {"X": 1, "seed": 7}, 7, "env-a")

    assert row is not None
    assert row["run_id"] == "orig"


def test_find_matching_run_no_hit_without_seeded_run(tmp_path):
    ws = _ws(tmp_path)
    row = run_index.find_matching_run(ws, "spec.a", {"X": 1}, None, "env-a")
    assert row is None


def test_find_matching_run_env_id_differs_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(ws, "spec.a", {"X": 1}, None, "env-b")

    assert row is None


def test_find_matching_run_config_mismatch_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(ws, "spec.a", {"X": 999}, None, "env-a")

    assert row is None


def test_find_matching_run_seed_mismatch_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": 7},
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(ws, "spec.a", {"X": 1}, 42, "env-a")

    assert row is None


def test_find_matching_run_non_completed_status_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint="fp1", status="running")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(ws, "spec.a", {"X": 1}, None, "env-a")

    assert row is None


def test_find_matching_run_missing_result_fingerprint_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint=None)
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(ws, "spec.a", {"X": 1}, None, "env-a")

    assert row is None


def test_find_matching_run_missing_artifact_is_a_miss(tmp_path):
    """Everything about the row matches — but its on-disk artifact was
    deleted (or never written, e.g. a faked/mocked launch in another test).
    This must never be 'retrieved'."""
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint="fp1")
    # deliberately no _make_artifact(ws, "orig") call

    row = run_index.find_matching_run(ws, "spec.a", {"X": 1}, None, "env-a")

    assert row is None


def test_find_matching_run_scans_study_runs_db(tmp_path):
    """A run recorded in a study's own runs.db (not the workspace-level
    composite-runs.db) is still found."""
    ws = tmp_path
    (ws / "workspace.yaml").write_text("name: ws\n")
    sd = ws / "studies" / "s1"
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text("name: s1\n")
    db = sd / "runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": 3},
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(ws, "spec.a", {"X": 1}, 3, "env-a")

    assert row is not None
    assert row["run_id"] == "orig"


def test_find_matching_run_picks_most_recent_on_ties(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    manifest = {"params": {"X": 1, "n_steps": 5}, "seed": None}
    _seed_run(db, "older", spec_id="spec.a", manifest=manifest,
              env_id="env-a", result_fingerprint="fp1")
    _seed_run(db, "newer", spec_id="spec.a", manifest=manifest,
              env_id="env-a", result_fingerprint="fp2")
    conn = cr.connect(db)
    conn.execute("UPDATE runs_meta SET started_at=1 WHERE run_id='older'")
    conn.execute("UPDATE runs_meta SET started_at=2 WHERE run_id='newer'")
    conn.commit()
    conn.close()
    _make_artifact(ws, "older")
    _make_artifact(ws, "newer")

    row = run_index.find_matching_run(ws, "spec.a", {"X": 1}, None, "env-a")

    assert row["run_id"] == "newer"


def test_find_matching_run_missing_spec_id_or_env_id_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    assert run_index.find_matching_run(ws, None, {}, None, "env-a") is None
    assert run_index.find_matching_run(ws, "spec.a", {}, None, None) is None

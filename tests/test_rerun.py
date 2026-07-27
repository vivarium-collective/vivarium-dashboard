# tests/test_rerun.py
"""verify_reproduction — compares two runs' result_fingerprint, gated on
matching env_id + seed (reproducible-rerun-spine Task 3 / G4, Step 6)."""
import json

from vivarium_workbench.lib import rerun, composite_runs as cr


def _seed_run(db_path, run_id, *, spec_id="s", params=None, env_id=None,
              result_fingerprint=None, status="completed"):
    """Insert a runs_meta row with the fields verify_reproduction reads.
    Mirrors test_rerun_resolve.py's ``_seed`` helper but goes through the
    real connect()/migration path so env_id/result_fingerprint columns exist,
    then sets them directly (save_metadata only derives env_id from a full
    manifest, which isn't needed for these unit tests)."""
    conn = cr.connect(db_path)
    conn.execute(
        "INSERT INTO runs_meta (run_id, spec_id, params_json, started_at, status, n_steps) "
        "VALUES (?,?,?,?,?,?)",
        (run_id, spec_id, json.dumps(params or {}), 0.0, status, 1),
    )
    conn.commit()
    conn.execute("UPDATE runs_meta SET env_id=?, result_fingerprint=? WHERE run_id=?",
                 (env_id, result_fingerprint, run_id))
    conn.commit()
    conn.close()


def test_verify_reproduction_match(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", params={"seed": 7}, env_id="env-a", result_fingerprint="fp1")
    _seed_run(db, "new", params={"seed": 7}, env_id="env-a", result_fingerprint="fp1")

    result = rerun.verify_reproduction(tmp_path, "orig", "new")

    assert result == {"match": True,
                       "reason": "result_fingerprint matches under identical env_id + seed"}
    conn = cr.connect(db)
    row = conn.execute(
        "SELECT provenance_status FROM runs_meta WHERE run_id='new'").fetchone()
    assert row[0] is None  # untouched on a match
    conn.close()


def test_verify_reproduction_real_mismatch_sets_nondeterministic(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", params={"seed": 7}, env_id="env-a", result_fingerprint="fp1")
    _seed_run(db, "new", params={"seed": 7}, env_id="env-a", result_fingerprint="fp2")

    result = rerun.verify_reproduction(tmp_path, "orig", "new")

    assert result["match"] is False
    assert "nondeterministic" in result["reason"]
    conn = cr.connect(db)
    row = conn.execute(
        "SELECT provenance_status FROM runs_meta WHERE run_id='new'").fetchone()
    assert row[0] == "nondeterministic"
    # the ORIGINAL run is untouched — only the reproduce (new) run is flagged
    row_orig = conn.execute(
        "SELECT provenance_status FROM runs_meta WHERE run_id='orig'").fetchone()
    assert row_orig[0] is None
    conn.close()


def test_verify_reproduction_env_id_differs_is_inconclusive_not_nondeterministic(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", params={"seed": 7}, env_id="env-a", result_fingerprint="fp1")
    _seed_run(db, "new", params={"seed": 7}, env_id="env-b", result_fingerprint="fp2")

    result = rerun.verify_reproduction(tmp_path, "orig", "new")

    assert result["match"] is None
    assert "env_id" in result["reason"]
    conn = cr.connect(db)
    row = conn.execute(
        "SELECT provenance_status FROM runs_meta WHERE run_id='new'").fetchone()
    assert row[0] is None  # a differing environment is NOT evidence of nondeterminism
    conn.close()


def test_verify_reproduction_seed_differs_is_inconclusive(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", params={"seed": 1}, env_id="env-a", result_fingerprint="fp1")
    _seed_run(db, "new", params={"seed": 2}, env_id="env-a", result_fingerprint="fp2")

    result = rerun.verify_reproduction(tmp_path, "orig", "new")

    assert result["match"] is None
    assert "seed" in result["reason"]


def test_verify_reproduction_missing_fingerprint_is_inconclusive(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", params={"seed": 7}, env_id="env-a", result_fingerprint=None)
    _seed_run(db, "new", params={"seed": 7}, env_id="env-a", result_fingerprint="fp2")

    result = rerun.verify_reproduction(tmp_path, "orig", "new")

    assert result["match"] is None
    assert "result_fingerprint" in result["reason"]


def test_verify_reproduction_run_not_found(tmp_path):
    (tmp_path / "workspace.yaml").write_text("layout:\n  studies: workspace/studies\n")
    db = tmp_path / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", params={"seed": 7}, env_id="env-a", result_fingerprint="fp1")

    result = rerun.verify_reproduction(tmp_path, "orig", "does-not-exist")

    assert result["match"] is None
    assert "not found" in result["reason"]

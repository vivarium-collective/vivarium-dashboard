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

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1, "seed": 7}, 7, "env-a", origin="composite")

    assert row is not None
    assert row["run_id"] == "orig"


def test_find_matching_run_no_hit_without_seeded_run(tmp_path):
    ws = _ws(tmp_path)
    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, None, "env-a", origin="composite")
    assert row is None


def test_find_matching_run_env_id_differs_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, None, "env-b", origin="composite")

    assert row is None


def test_find_matching_run_config_mismatch_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 999}, None, "env-a", origin="composite")

    assert row is None


def test_find_matching_run_seed_mismatch_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": 7},
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, 42, "env-a", origin="composite")

    assert row is None


def test_find_matching_run_non_completed_status_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint="fp1", status="running")
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, None, "env-a", origin="composite")

    assert row is None


def test_find_matching_run_missing_result_fingerprint_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    db = ws / ".pbg" / "composite-runs.db"
    _seed_run(db, "orig", spec_id="spec.a",
              manifest={"params": {"X": 1, "n_steps": 5}, "seed": None},
              env_id="env-a", result_fingerprint=None)
    _make_artifact(ws, "orig")

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, None, "env-a", origin="composite")

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

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, None, "env-a", origin="composite")

    assert row is None


def test_find_matching_run_finds_a_study_origin_run_in_its_own_db(tmp_path):
    """A run recorded in a study's own runs.db (not the workspace-level
    composite-runs.db), looked up with origin='study'/study='s1', is
    found."""
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

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, 3, "env-a", origin="study", study="s1")

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

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, None, "env-a", origin="composite")

    assert row["run_id"] == "newer"


def test_find_matching_run_missing_spec_id_or_env_id_is_a_miss(tmp_path):
    ws = _ws(tmp_path)
    assert run_index.find_matching_run(
        ws, None, {}, None, "env-a", origin="composite") is None
    assert run_index.find_matching_run(
        ws, "spec.a", {}, None, None, origin="composite") is None


# ---------------------------------------------------------------------------
# Review round 1, Finding 1 — retrieval must be scoped to the run's OWN
# owning DB (workspace composite-runs.db for a composite-origin run, that
# specific study's runs.db for a study-origin run). A sibling study sharing
# the same baseline composite/params/seed/env must NEVER be "retrieved" —
# such a hit would stay tagged to the FOREIGN study, invisible in the
# reproducing study's own /api/simulations list and Simulations tab.
# ---------------------------------------------------------------------------

def test_find_matching_run_ignores_an_identical_match_in_a_different_study(tmp_path):
    """s2 has a completed, intact run that is byte-for-byte identical
    (spec_id/config/seed/env_id/fingerprint) to what a reproduce under s1
    would look for. It must NOT be returned when looking up s1 — s1's own
    runs.db has no matching run of its own."""
    ws = tmp_path
    (ws / "workspace.yaml").write_text("name: ws\n")
    manifest = {"params": {"X": 1, "n_steps": 5}, "seed": 3}

    for slug in ("s1", "s2"):
        sd = ws / "studies" / slug
        sd.mkdir(parents=True)
        (sd / "study.yaml").write_text(f"name: {slug}\n")

    db2 = ws / "studies" / "s2" / "runs.db"
    _seed_run(db2, "foreign", spec_id="spec.a", manifest=manifest,
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "foreign")

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, 3, "env-a", origin="study", study="s1")

    assert row is None


def test_find_matching_run_prefers_the_owning_study_over_a_sibling(tmp_path):
    """Both s1 and s2 have an identically-configured completed run. Looking
    up under s1 must return s1's OWN run, never s2's — even though s2's
    would also satisfy every other criterion."""
    ws = tmp_path
    (ws / "workspace.yaml").write_text("name: ws\n")
    manifest = {"params": {"X": 1, "n_steps": 5}, "seed": 3}

    for slug, run_id in (("s1", "own"), ("s2", "foreign")):
        sd = ws / "studies" / slug
        sd.mkdir(parents=True)
        (sd / "study.yaml").write_text(f"name: {slug}\n")
        db = sd / "runs.db"
        _seed_run(db, run_id, spec_id="spec.a", manifest=manifest,
                  env_id="env-a", result_fingerprint="fp1")
        _make_artifact(ws, run_id)

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, 3, "env-a", origin="study", study="s1")

    assert row is not None
    assert row["run_id"] == "own"


def test_find_matching_run_composite_origin_ignores_study_dbs(tmp_path):
    """A composite-origin lookup (origin='composite') must only look in
    the workspace-level composite-runs.db — an identically-configured run
    sitting in some study's runs.db must not be returned."""
    ws = tmp_path
    (ws / "workspace.yaml").write_text("name: ws\n")
    sd = ws / "studies" / "s1"
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text("name: s1\n")
    db = sd / "runs.db"
    manifest = {"params": {"X": 1, "n_steps": 5}, "seed": 3}
    _seed_run(db, "study-run", spec_id="spec.a", manifest=manifest,
              env_id="env-a", result_fingerprint="fp1")
    _make_artifact(ws, "study-run")

    row = run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, 3, "env-a", origin="composite")

    assert row is None


def test_find_matching_run_study_origin_missing_study_is_a_miss(tmp_path):
    """origin='study' with no (or an unresolvable) study slug can't be
    scoped to exactly one DB — degrades to no match rather than guessing
    or falling back to a scan."""
    ws = _ws(tmp_path)
    assert run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, None, "env-a", origin="study", study=None) is None
    assert run_index.find_matching_run(
        ws, "spec.a", {"X": 1}, None, "env-a", origin="study", study="no-such-study") is None


# ---------------------------------------------------------------------------
# Review round 1, Finding 2 — row_seed / replay_params are the ONE shared
# derivation find_matching_run's match key and rerun.resolve_rerun_target's
# actual replay inputs both go through (see test_rerun.py for the
# cross-module consistency proof).
# ---------------------------------------------------------------------------

def test_row_seed_prefers_manifest_seed():
    row = {"params": {"seed": 999}, "manifest_json": json.dumps({"seed": 7})}
    assert run_index.row_seed(row) == 7


def test_row_seed_falls_back_to_params_without_manifest():
    row = {"params": {"seed": 3}, "manifest_json": None}
    assert run_index.row_seed(row) == 3


def test_row_seed_falls_back_to_params_when_manifest_seed_null():
    row = {"params": {"seed": 3}, "manifest_json": json.dumps({"seed": None})}
    assert run_index.row_seed(row) == 3


def test_replay_params_strips_n_steps_and_prefers_manifest():
    row = {
        "params": {"X": 999, "n_steps": 999},
        "manifest_json": json.dumps({"params": {"X": 1, "seed": 7, "n_steps": 5}}),
    }
    params, n_steps = run_index.replay_params(row)
    assert params == {"X": 1, "seed": 7}
    assert n_steps == 5


def test_replay_params_falls_back_to_legacy_params_json(tmp_path):
    row = {"params": {"X": 1, "n_steps": 3}, "manifest_json": None, "n_steps": 3}
    params, n_steps = run_index.replay_params(row)
    assert params == {"X": 1}
    assert n_steps == 3

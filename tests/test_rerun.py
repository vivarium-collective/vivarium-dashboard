# tests/test_rerun.py
"""verify_reproduction — compares two runs' result_fingerprint, gated on
matching env_id + seed (reproducible-rerun-spine Task 3 / G4, Step 6)."""
import json

import yaml

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


def test_verify_reproduction_reads_first_class_seed_from_manifest():
    # reproducible-rerun-spine Task 4: verify_reproduction's seed-match must
    # read the recorded manifest's first-class "seed" (not params["seed"])
    # once one is present — a row with a manifest seed that DISAGREES with
    # params["seed"] (shouldn't happen in practice, but proves precedence)
    # is compared on the manifest's value.
    orig = {"params": {"seed": 999}, "manifest_json": json.dumps({"seed": 7})}
    new = {"params": {"seed": 999}, "manifest_json": json.dumps({"seed": 7})}
    assert rerun._row_seed(orig) == 7
    assert rerun._row_seed(new) == 7


def test_row_seed_falls_back_to_params_without_manifest():
    row = {"params": {"seed": 3}, "manifest_json": None}
    assert rerun._row_seed(row) == 3


def test_row_seed_falls_back_to_params_when_manifest_seed_null():
    row = {"params": {"seed": 3}, "manifest_json": json.dumps({"seed": None})}
    assert rerun._row_seed(row) == 3


# ---------------------------------------------------------------------------
# reproducible-rerun-spine Task 4 / G2 — Reproduce == replay the manifest,
# NEVER re-derive from the study's current study.yaml.
# ---------------------------------------------------------------------------

def test_reproduce_replays_manifest_not_current_yaml(tmp_path, monkeypatch):
    """The key Task 4 proof: Reproduce forwards the ORIGINAL run's recorded
    manifest (params/seed) verbatim, even after study.yaml is edited —
    proving Reproduce != re-derive.

    Driven through the REAL live routes (FastAPI TestClient, in-process) —
    ``POST /api/study-run-baseline`` then ``POST /api/study-reproduce`` — so
    this exercises the actual endpoint wiring, not just the lib function.
    The generator registry and the composite's own subprocess are faked
    (``conftest.register_generator`` / a monkeypatched ``subprocess.run``),
    the same convention ``test_composite_subprocess_lib.py`` uses: a
    ``@composite_generator`` is only real-process-discoverable when its
    hosting package is a genuinely pip-installed distribution (`discover_
    generators` walks `importlib.metadata.distributions()`), which a bare
    fixture workspace on `sys.path` is not — faking the registry avoids
    that environment gap without weakening what THIS test actually proves
    (manifest replay fidelity, not composite-generator discovery)."""
    import types
    from fastapi.testclient import TestClient
    from conftest import register_generator
    import viva_superpowers.composite_generator as cg
    from vivarium_workbench.api.app import create_app, get_workspace
    from vivarium_workbench.lib import composite_subprocess as cs
    from vivarium_workbench.lib import cli_runs

    spec_id = "test.reproduce.demo"
    monkeypatch.setattr(cg, "discover_generators", lambda *a, **k: None)
    register_generator(spec_id, parameters={"X": {}, "seed": {}})

    def _fake_run(cmd, **kwargs):
        payload = {"results": {}, "viz_html": {}}
        return types.SimpleNamespace(
            returncode=0, stdout="@@@RESULTS@@@\n" + json.dumps(payload), stderr="")
    monkeypatch.setattr(cs.subprocess, "run", _fake_run)

    ws = tmp_path
    (ws / "workspace.yaml").write_text(yaml.safe_dump(
        {"schema_version": 2, "name": "ws", "package_path": "testpkg"}))
    sd = ws / "studies" / "s1"
    sd.mkdir(parents=True)
    spec_file = sd / "study.yaml"
    spec_file.write_text(yaml.safe_dump({
        "schema_version": 3, "name": "s1", "created": "2026-07-27",
        "status": "draft", "objective": "",
        "baseline": [
            {"name": "core", "composite": spec_id,
             "params": {"X": 1, "seed": 7, "n_steps": 1}},
        ],
        "variants": [], "runs": [], "visualizations": [], "comparisons": [],
        "conclusion": None, "parent_studies": [], "interventions": [],
    }))

    app = create_app()
    app.dependency_overrides[get_workspace] = lambda: ws
    client = TestClient(app)

    resp = client.post("/api/study-run-baseline", json={"study": "s1"})
    assert resp.status_code == 200, resp.text
    original_run_id = resp.json()["simulation_id"]

    # Mutate study.yaml AFTER the original run — Reproduce must ignore this.
    spec = yaml.safe_load(spec_file.read_text())
    spec["baseline"][0]["params"]["X"] = 999
    spec["baseline"][0]["params"]["seed"] = 42
    spec_file.write_text(yaml.safe_dump(spec))

    resp = client.post("/api/study-reproduce",
                       json={"study": "s1", "run_id": original_run_id})
    assert resp.status_code == 200, resp.text
    new_run_id = resp.json()["simulation_id"]
    assert new_run_id != original_run_id  # always mints a NEW run_id

    _db, row = cli_runs.find_run(ws, new_run_id)
    assert row is not None
    manifest = json.loads(row["manifest_json"])
    assert manifest["params"]["X"] == 1
    assert manifest["seed"] == 7


# ---------------------------------------------------------------------------
# reproducible-rerun-spine Task 5 / G3 — env-drift detection + pinned_env.
# ---------------------------------------------------------------------------

def _reproduce_under_drifting_env(tmp_path, monkeypatch, *, pinned_env=None):
    """Shared scaffold: launch a baseline, force the env digest to change
    ("env-A" -> "env-B") between that launch and a subsequent Reproduce, and
    return (ws, original_run_id, new_run_id, new_run_row).

    Faking ``env_fingerprint.env_id`` (rather than ``compute_env``) is enough
    to make the ORIGINAL run's stamped env_id ("env-A", the first call)
    differ from both the REPLAY's own stamped env_id and Task 5's
    independent drift-check recomputation (every later call, "env-B") —
    exactly the "different environment" scenario env_stale detects, without
    depending on any real git/package state in the test sandbox.
    """
    import types
    from fastapi.testclient import TestClient
    from conftest import register_generator
    import viva_superpowers.composite_generator as cg
    from vivarium_workbench.api.app import create_app, get_workspace
    from vivarium_workbench.lib import composite_subprocess as cs
    from vivarium_workbench.lib import cli_runs, env_fingerprint

    spec_id = "test.envstale.demo"
    monkeypatch.setattr(cg, "discover_generators", lambda *a, **k: None)
    register_generator(spec_id, parameters={"X": {}, "seed": {}})

    def _fake_run(cmd, **kwargs):
        payload = {"results": {}, "viz_html": {}}
        return types.SimpleNamespace(
            returncode=0, stdout="@@@RESULTS@@@\n" + json.dumps(payload), stderr="")
    monkeypatch.setattr(cs.subprocess, "run", _fake_run)

    calls = {"n": 0}

    def _fake_env_id(env):
        calls["n"] += 1
        return "env-A" if calls["n"] == 1 else "env-B"
    monkeypatch.setattr(env_fingerprint, "env_id", _fake_env_id)

    ws = tmp_path
    (ws / "workspace.yaml").write_text(yaml.safe_dump(
        {"schema_version": 2, "name": "ws", "package_path": "testpkg"}))
    sd = ws / "studies" / "s1"
    sd.mkdir(parents=True)
    spec_file = sd / "study.yaml"
    spec = {
        "schema_version": 3, "name": "s1", "created": "2026-07-27",
        "status": "draft", "objective": "",
        "baseline": [
            {"name": "core", "composite": spec_id,
             "params": {"X": 1, "seed": 7, "n_steps": 1}},
        ],
        "variants": [], "runs": [], "visualizations": [], "comparisons": [],
        "conclusion": None, "parent_studies": [], "interventions": [],
    }
    if pinned_env is not None:
        spec["pinned_env"] = pinned_env
    spec_file.write_text(yaml.safe_dump(spec))

    app = create_app()
    app.dependency_overrides[get_workspace] = lambda: ws
    client = TestClient(app)

    resp = client.post("/api/study-run-baseline", json={"study": "s1"})
    assert resp.status_code == 200, resp.text
    original_run_id = resp.json()["simulation_id"]

    resp = client.post("/api/study-reproduce",
                       json={"study": "s1", "run_id": original_run_id})
    assert resp.status_code == 200, resp.text
    new_run_id = resp.json()["simulation_id"]

    _db, row = cli_runs.find_run(ws, new_run_id)
    assert row is not None
    return ws, original_run_id, new_run_id, row


def test_reproduce_sets_env_stale_when_environment_differs(tmp_path, monkeypatch):
    """Task 5's key proof: a run stamped at env A, reproduced under env B,
    gets its ``provenance_status`` flagged ``'env_stale'`` — a best-effort
    pre-check independent of (and never blocking) the rerun itself."""
    _ws, _orig, _new, row = _reproduce_under_drifting_env(tmp_path, monkeypatch)
    assert row["provenance_status"] == "env_stale"


def test_reproduce_pinned_env_suppresses_env_stale(tmp_path, monkeypatch):
    """A study.yaml ``pinned_env:`` matching the ORIGINAL run's env_id is an
    accepted/pinned drift — env_stale must NOT be stamped."""
    _ws, _orig, _new, row = _reproduce_under_drifting_env(
        tmp_path, monkeypatch, pinned_env="env-A")
    assert row["provenance_status"] != "env_stale"

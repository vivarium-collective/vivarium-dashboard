import json
from vivarium_workbench.lib import composite_runs as cr


def test_migration_adds_manifest_column(tmp_path):
    conn = cr.connect(tmp_path / "runs.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs_meta)")}
    assert "manifest_json" in cols


def test_save_metadata_writes_manifest(tmp_path):
    conn = cr.connect(tmp_path / "runs.db")
    manifest = {"version": 1, "spec_id": "s", "params": {"seed": 0, "cache_dir": "out/cache"},
                "n_steps": 100, "emitter": "parquet", "emit_paths": ["bulk"],
                "runtime": {"emitter": "parquet"}, "origin": "study", "study": "s1"}
    cr.save_metadata(conn, spec_id="s", run_id="r1", params={"seed": 0}, label="b",
                     started_at=0.0, n_steps=100, manifest=manifest)
    row = conn.execute("SELECT manifest_json FROM runs_meta WHERE run_id='r1'").fetchone()
    assert json.loads(row[0])["emitter"] == "parquet"
    assert json.loads(row[0])["params"]["cache_dir"] == "out/cache"


def test_save_metadata_no_manifest_is_null(tmp_path):
    conn = cr.connect(tmp_path / "runs.db")
    cr.save_metadata(conn, spec_id="s", run_id="r2", params={"seed": 0}, label="b",
                     started_at=0.0, n_steps=100)
    row = conn.execute("SELECT manifest_json FROM runs_meta WHERE run_id='r2'").fetchone()
    assert row[0] is None


def test_build_run_manifest_shape():
    m = cr.build_run_manifest(spec_id="s", params={"seed": 0}, n_steps=100,
                              emitter="parquet", emit_paths=["bulk"], runtime={"x": 1},
                              origin="study", study="s1", pkg="v2ecoli", generation_id=None)
    for k in ("version", "spec_id", "params", "n_steps", "emitter", "emit_paths",
              "runtime", "origin", "study", "pkg", "code_version"):
        assert k in m


def test_build_run_manifest_is_version_2_with_null_placeholders():
    # reproducible-rerun-spine Task 1: manifest schema bumped to v2 with new
    # keys filled in by later tasks (env=Task 2 [now populated, see below],
    # fingerprint=Task 3, seed=Task 4) — those two are still null here.
    m = cr.build_run_manifest(spec_id="s", params={"seed": 0}, n_steps=100,
                              emitter="parquet", emit_paths=["bulk"], runtime={"x": 1},
                              origin="study", study="s1", pkg="v2ecoli", generation_id=None)
    assert m["version"] == 2
    for k in ("seed", "fingerprint_fields", "result_fingerprint"):
        assert k in m
        assert m[k] is None


def test_build_run_manifest_code_version_best_effort_ok_without_ws_root():
    # No ws_root / unresolvable pkg → code_version degrades to Nones, never raises.
    m = cr.build_run_manifest(spec_id="s", params={}, n_steps=1,
                              emitter=None, emit_paths=[], runtime={},
                              origin="composite")
    assert m["code_version"]["git_sha"] is None
    assert m["code_version"]["package"] is None


# --- env / env_id (reproducible-rerun-spine Task 2) ------------------------

def test_build_run_manifest_populates_env():
    # env is no longer a null placeholder: it's a compute_env() dict, always
    # present with the documented keys, even without ws_root/cache_fingerprint.
    m = cr.build_run_manifest(spec_id="s", params={}, n_steps=1,
                              emitter=None, emit_paths=[], runtime={},
                              origin="composite")
    assert isinstance(m["env"], dict)
    for k in ("workspace_commit", "sim_packages", "lockfile_hash", "python",
              "platform", "cache_fingerprint"):
        assert k in m["env"]


def test_build_run_manifest_threads_explicit_cache_fingerprint(tmp_path):
    (tmp_path / "uv.lock").write_text("lock")
    m = cr.build_run_manifest(spec_id="s", params={}, n_steps=1,
                              emitter=None, emit_paths=[], runtime={},
                              origin="composite", ws_root=tmp_path,
                              cache_fingerprint="cf-explicit")
    assert m["env"]["cache_fingerprint"] == "cf-explicit"
    assert m["env"]["lockfile_hash"] is not None


def test_build_run_manifest_sniffs_cache_fingerprint_from_params():
    # v2ecoli's run_condition_multigen_parquet.py threads its already-computed
    # cache fingerprint scalar onto params["cache_fingerprint"] — build_run_manifest
    # picks it up when no explicit cache_fingerprint kwarg is given.
    m = cr.build_run_manifest(spec_id="s", params={"cache_fingerprint": "cf-from-params"},
                              n_steps=1, emitter=None, emit_paths=[], runtime={},
                              origin="composite")
    assert m["env"]["cache_fingerprint"] == "cf-from-params"


def test_migration_adds_env_id_column(tmp_path):
    conn = cr.connect(tmp_path / "runs.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs_meta)")}
    assert "env_id" in cols


def test_save_metadata_writes_env_id_from_manifest_env(tmp_path):
    conn = cr.connect(tmp_path / "runs.db")
    manifest = cr.build_run_manifest(spec_id="s", params={}, n_steps=1,
                                     emitter=None, emit_paths=[], runtime={},
                                     origin="composite")
    cr.save_metadata(conn, spec_id="s", run_id="r3", params={}, label="b",
                     started_at=0.0, n_steps=1, manifest=manifest)
    row = conn.execute("SELECT env_id FROM runs_meta WHERE run_id='r3'").fetchone()
    assert row[0] is not None
    assert len(row[0]) == 16


def test_save_metadata_no_manifest_env_id_is_null(tmp_path):
    conn = cr.connect(tmp_path / "runs.db")
    cr.save_metadata(conn, spec_id="s", run_id="r4", params={"seed": 0}, label="b",
                     started_at=0.0, n_steps=100)
    row = conn.execute("SELECT env_id FROM runs_meta WHERE run_id='r4'").fetchone()
    assert row[0] is None

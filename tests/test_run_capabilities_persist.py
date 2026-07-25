import json
from vivarium_workbench.lib import composite_runs


def test_migration_adds_column(tmp_path):
    db = tmp_path / "runs.db"
    conn = composite_runs.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs_meta)")}
    assert "capabilities_json" in cols


def test_write_and_read_capabilities(tmp_path):
    db = tmp_path / "runs.db"
    conn = composite_runs.connect(db)
    conn.execute(
        "INSERT INTO runs_meta (run_id, spec_id, started_at, status) "
        "VALUES ('r1','s1',0.0,'completed')")
    composite_runs.write_run_capabilities(conn, "r1", ["observables", "mass"])
    row = conn.execute(
        "SELECT capabilities_json FROM runs_meta WHERE run_id='r1'").fetchone()
    assert json.loads(row[0]) == ["observables", "mass"]

"""Unit tests for vivarium_dashboard.lib.simulations_index."""
from pathlib import Path

import yaml

from vivarium_dashboard.lib.composite_runs import connect, save_metadata
from vivarium_dashboard.lib.simulations_index import list_simulations


def _seed_run(db_file, *, spec_id, run_id, started_at, sim_name=None):
    conn = connect(db_file)
    save_metadata(conn, spec_id=spec_id, run_id=run_id, params={}, label="",
                  started_at=started_at, n_steps=3, log_path=None)
    if sim_name:
        conn.execute("UPDATE runs_meta SET sim_name=? WHERE run_id=?",
                     (sim_name, run_id))
        conn.commit()
    conn.close()


def test_list_walks_workspace_and_studies_dbs(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".pbg").mkdir(parents=True)
    (ws / "studies" / "foo").mkdir(parents=True)
    _seed_run(ws / ".pbg" / "composite-runs.db",
              spec_id="pkg.x", run_id="r-scratch", started_at=10.0)
    _seed_run(ws / "studies" / "foo" / "runs.db",
              spec_id="pkg.y", run_id="r-baseline", started_at=20.0,
              sim_name="baseline")

    sims = list_simulations(ws)
    ids = [s["run_id"] for s in sims]
    assert ids == ["r-baseline", "r-scratch"]   # newest first
    assert sims[0]["db_path"] == "studies/foo/runs.db"
    assert sims[1]["db_path"] == ".pbg/composite-runs.db"
    assert sims[0]["sim_name"] == "baseline"
    # No study.yaml yet → empty studies annotation
    assert all(s["studies"] == [] for s in sims)


def test_list_cross_references_study_yaml_list_form(tmp_path):
    ws = tmp_path / "ws"
    (ws / "studies" / "foo").mkdir(parents=True)
    _seed_run(ws / "studies" / "foo" / "runs.db",
              spec_id="pkg.y", run_id="r-1", started_at=1.0)
    (ws / "studies" / "foo" / "study.yaml").write_text(
        yaml.safe_dump({"name": "foo", "runs": ["r-1"]}))

    sims = list_simulations(ws)
    assert len(sims) == 1
    assert sims[0]["studies"] == ["foo"]


def test_list_cross_references_study_yaml_dict_form(tmp_path):
    ws = tmp_path / "ws"
    (ws / "studies" / "foo").mkdir(parents=True)
    _seed_run(ws / "studies" / "foo" / "runs.db",
              spec_id="pkg.y", run_id="r-1", started_at=1.0)
    (ws / "studies" / "foo" / "study.yaml").write_text(
        yaml.safe_dump({"name": "foo",
                        "runs": [{"run_id": "r-1", "label": "baseline"}]}))

    sims = list_simulations(ws)
    assert sims[0]["studies"] == ["foo"]


def test_list_run_referenced_by_multiple_studies(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".pbg").mkdir(parents=True)
    _seed_run(ws / ".pbg" / "composite-runs.db",
              spec_id="pkg.x", run_id="shared", started_at=1.0)
    for name in ("alpha", "beta"):
        sdir = ws / "studies" / name
        sdir.mkdir(parents=True)
        (sdir / "study.yaml").write_text(
            yaml.safe_dump({"name": name, "runs": ["shared"]}))

    sims = list_simulations(ws)
    assert sims[0]["studies"] == ["alpha", "beta"]


def test_list_tolerates_missing_dbs(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    # No .pbg/, no studies/ — should not raise
    assert list_simulations(ws) == []


def test_list_tolerates_malformed_study_yaml(tmp_path):
    ws = tmp_path / "ws"
    (ws / "studies" / "foo").mkdir(parents=True)
    _seed_run(ws / "studies" / "foo" / "runs.db",
              spec_id="pkg.y", run_id="r-1", started_at=1.0)
    (ws / "studies" / "foo" / "study.yaml").write_text("not: [valid: yaml")

    sims = list_simulations(ws)
    # The run still shows up; studies annotation is empty (yaml unparseable)
    assert len(sims) == 1
    assert sims[0]["studies"] == []

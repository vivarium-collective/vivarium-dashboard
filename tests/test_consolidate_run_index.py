"""Consolidate the per-study run list onto the .pbg/runs.jsonl index.

Covers:
- read_runs_db_for_study now folds the workspace-wide `.pbg/runs.jsonl`
  (study-filtered) so jsonl-only runs (bespoke/remote) appear, while runs.db
  stays authoritative where both have a row.
- load_study_detail_spec dedups a run present in BOTH study.yaml `runs:` (keyed
  by `name`) and the run-index (keyed by `run_id`) — the old merge produced two
  rows — while preserving the study.yaml entry's authored outcomes/provenance.
- run_index_slugs_from_db_path derives (study_slug, investigation_slug) so runs
  are tagged in the jsonl at write time.
"""
from pathlib import Path

import yaml

from vivarium_workbench.lib import composite_runs, run_log
from vivarium_workbench.lib.study_spec import (
    read_runs_db_for_study, load_study_detail_spec,
)
from vivarium_workbench.lib.composite_subprocess import run_index_slugs_from_db_path


def _study(ws: Path, slug: str, spec: dict) -> Path:
    d = ws / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.yaml").write_text(yaml.safe_dump(spec))
    return d


def test_read_runs_includes_jsonl_only_run_tagged_for_study(tmp_path: Path):
    _study(tmp_path, "s01", {"schema_version": 4, "name": "s01"})
    # A run that lives ONLY in the workspace jsonl index (no runs.db, no
    # study.yaml runs:) — e.g. a bespoke pbg_runner or remote run — tagged for
    # this study must now surface in the per-study list.
    run_log.append_run_event(tmp_path, {
        "run_id": "spec__1__jsononly", "event": "started", "spec_id": "spec",
        "status": "completed", "started_at": 5.0, "n_steps": 3,
        "study_slug": "s01", "params": {"seed": 0}})
    rows = read_runs_db_for_study(tmp_path, "s01")
    row = next((r for r in rows if r["run_id"] == "spec__1__jsononly"), None)
    assert row is not None, "jsonl-only run tagged for this study should appear"
    assert row["source"] == "runs.jsonl"
    assert row["status"] == "completed"


def test_read_runs_ignores_jsonl_run_tagged_for_other_study(tmp_path: Path):
    _study(tmp_path, "s01", {"schema_version": 4, "name": "s01"})
    run_log.append_run_event(tmp_path, {
        "run_id": "other__1__x", "event": "started", "status": "completed",
        "study_slug": "s02", "started_at": 1.0})
    ids = {r["run_id"] for r in read_runs_db_for_study(tmp_path, "s01")}
    assert "other__1__x" not in ids


def test_read_runs_jsonl_does_not_override_runs_db(tmp_path: Path):
    _study(tmp_path, "s01", {"schema_version": 4, "name": "s01"})
    db = tmp_path / "studies" / "s01" / "runs.db"
    conn = composite_runs.connect(db)
    composite_runs.save_metadata(
        conn, spec_id="spec", run_id="spec__1__a", params={"seed": 7},
        label="baseline", started_at=2.0, n_steps=9)  # runs.db only (no ws=)
    # A stale jsonl 'started' for the same id must NOT clobber the runs.db row.
    run_log.append_run_event(tmp_path, {
        "run_id": "spec__1__a", "event": "started", "status": "running",
        "study_slug": "s01"})
    rows = {r["run_id"]: r for r in read_runs_db_for_study(tmp_path, "s01")}
    assert rows["spec__1__a"]["source"] == "runs_meta"      # runs.db wins
    assert rows["spec__1__a"]["params"].get("seed") == 7


def test_load_study_detail_dedups_yaml_and_db_and_keeps_outcomes(tmp_path: Path):
    rid = "spec__1__dup"
    _study(tmp_path, "s01", {
        "schema_version": 4, "name": "s01",
        "question": "q",
        "conditions": {"baseline": {"composite": "spec", "params": {}}},
        "runs": [{
            "name": rid, "status": "completed",
            "outcomes": {"GROWTH": "pass"},
            "provenance": {"params_source": "dashboard-runner"},
        }],
    })
    db = tmp_path / "studies" / "s01" / "runs.db"
    conn = composite_runs.connect(db)
    composite_runs.save_metadata(
        conn, spec_id="spec", run_id=rid, params={}, label="baseline",
        started_at=3.0, n_steps=5)
    composite_runs.complete_metadata(
        conn, run_id=rid, n_steps=5, status="completed")

    spec = load_study_detail_spec(tmp_path, "s01")
    matching = [r for r in spec["runs"]
                if (r.get("run_id") or r.get("name")) == rid]
    assert len(matching) == 1, (
        f"run present in both study.yaml (name) and runs.db (run_id) must appear "
        f"ONCE, got {len(matching)}")
    # Authored outcomes/provenance grafted onto the canonical run-index row.
    assert matching[0].get("outcomes") == {"GROWTH": "pass"}
    assert matching[0].get("provenance", {}).get("params_source") == "dashboard-runner"


def test_run_index_slugs_from_db_path():
    assert run_index_slugs_from_db_path("/w/studies/s01/runs.db") == ("s01", None)
    assert run_index_slugs_from_db_path(
        "/w/investigations/inv-a/studies/s02/runs.db") == ("s02", "inv-a")
    assert run_index_slugs_from_db_path("/w/.pbg/composite-runs.db") == (None, None)

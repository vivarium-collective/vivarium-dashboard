"""``db_exists`` must reflect an actual PLOTTABLE run store, not a bare
``runs.db`` file-existence check.

``studies/<slug>/runs.db`` is created for run *metadata* on every run
regardless of emitter (``composite_runs.connect``); it only doubles as chart
data when the sqlite emitter's ``history`` table is populated. The framework
default emitter is xarray/zarr (``lib/emitters.py:DEFAULT_EMITTER``), and
every remote/Ray-dispatched run is zarr-only — for those, ``runs.db`` exists
(metadata) but never gets a populated ``history`` table. A bare
``runs_db.exists()`` check therefore reports "data exists" for a
metadata-only db and "no data" for a real zarr-backed run — both wrong.

These tests exercise ``build_study_charts_payload``'s ``db_exists`` (and the
accompanying ``data_store`` diagnostic) against the emitter broker's actual
resolution, per ``lib/emitters.py`` (``default_emitter``/``output_kind``),
reusing ``study_charts``'s own store-detection helpers rather than
constructing real zarr/parquet libraries.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from vivarium_workbench.lib.study_charts import build_study_charts_payload as _payload


def _write_runs_meta_only(study_dir: Path, run_id: str) -> None:
    """A ``runs.db`` with ONLY the ``runs_meta`` table — metadata, no trajectory
    data. Mirrors what every run (local or remote) writes regardless of
    emitter — see ``composite_runs.connect``."""
    db = study_dir / "runs.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE runs_meta (run_id TEXT, started_at REAL, "
            "completed_at REAL, status TEXT)"
        )
        conn.execute(
            "INSERT INTO runs_meta (run_id, started_at, completed_at, status) "
            "VALUES (?, ?, ?, ?)",
            (run_id, 1.0, 2.0, "completed"),
        )
        conn.commit()
    finally:
        conn.close()


def _write_populated_history(study_dir: Path, run_id: str) -> None:
    """A ``runs.db`` whose ``history`` table (the sqlite emitter's trajectory
    table) has real rows — the case ``db_exists`` must recognize as real
    plottable data."""
    db = study_dir / "runs.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE runs_meta (run_id TEXT, started_at REAL, "
            "completed_at REAL, status TEXT)"
        )
        conn.execute(
            "INSERT INTO runs_meta (run_id, started_at, completed_at, status) "
            "VALUES (?, ?, ?, ?)",
            (run_id, 1.0, 2.0, "completed"),
        )
        conn.execute(
            "CREATE TABLE history (simulation_id INTEGER, step INTEGER, "
            "global_time REAL, state TEXT)"
        )
        conn.execute(
            "INSERT INTO history (simulation_id, step, global_time, state) "
            "VALUES (1, 1, 1.0, '{}')"
        )
        conn.commit()
    finally:
        conn.close()


def _write_zarr_store(study_dir: Path, run_id: str) -> None:
    """A zarr store dir at the canonical ``runs.<run_id>.zarr`` convention with
    a populated ``experiment_id=*`` partition — enough for
    ``study_charts._latest_zarr_for_study`` (a plain glob/existence probe, no
    zarr library needed) to consider it real data."""
    zarr_dir = study_dir / f"runs.{run_id}.zarr"
    (zarr_dir / "experiment_id=exp0").mkdir(parents=True)


def _write_study_yaml(study_dir: Path, *, default_emitter: str | None = None) -> None:
    spec: dict = {"name": study_dir.name}
    if default_emitter:
        spec["runtime"] = {"default_emitter": default_emitter}
    (study_dir / "study.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")


def test_db_exists_true_for_zarr_only_store(tmp_path: Path):
    """Metadata-only runs.db + a real zarr store (workspace on xarray) →
    db_exists True. The bare ``runs_db.exists()`` check would ALSO say True
    here (accidentally, since runs.db is present) — the real assertion is
    that data_store correctly names zarr as the honest reason, proving the
    broker path (not file presence) drove the answer."""
    ws = tmp_path / "ws"
    study_dir = ws / "studies" / "zarr-demo"
    study_dir.mkdir(parents=True)
    _write_study_yaml(study_dir, default_emitter="xarray")
    _write_runs_meta_only(study_dir, "run-1")
    _write_zarr_store(study_dir, "run-1")

    payload = _payload(ws, "zarr-demo")
    assert payload["db_exists"] is True
    assert payload["data_store"] == "zarr"


def test_db_exists_true_for_populated_sqlite_history(tmp_path: Path):
    """A study with a populated sqlite ``history`` table → db_exists True."""
    ws = tmp_path / "ws"
    study_dir = ws / "studies" / "sqlite-demo"
    study_dir.mkdir(parents=True)
    _write_study_yaml(study_dir, default_emitter="sqlite")
    _write_populated_history(study_dir, "run-1")

    payload = _payload(ws, "sqlite-demo")
    assert payload["db_exists"] is True
    assert payload["data_store"] == "sqlite"


def test_db_exists_false_for_metadata_only_runs_db(tmp_path: Path):
    """THE regression case: a runs.db that holds ONLY run metadata (no
    history rows, no zarr, no parquet) must yield db_exists False — a bare
    ``runs_db.exists()`` check would wrongly say True here, since the file is
    on disk. This is the misleading case the task is fixing."""
    ws = tmp_path / "ws"
    study_dir = ws / "studies" / "meta-only-demo"
    study_dir.mkdir(parents=True)
    _write_study_yaml(study_dir)
    _write_runs_meta_only(study_dir, "run-1")

    payload = _payload(ws, "meta-only-demo")
    assert payload["db_exists"] is False
    assert payload["data_store"] is None


def test_db_exists_false_for_nothing(tmp_path: Path):
    """No runs.db, no zarr, no parquet, no study.yaml at all → db_exists False."""
    ws = tmp_path / "ws"
    (ws / "studies" / "empty-demo").mkdir(parents=True)

    payload = _payload(ws, "empty-demo")
    assert payload["db_exists"] is False
    assert payload["data_store"] is None

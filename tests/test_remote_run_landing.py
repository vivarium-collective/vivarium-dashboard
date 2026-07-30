import json
import sqlite3
import tarfile
from pathlib import Path

from vivarium_workbench.lib.remote_run_landing import land_remote_run


def _make_remote_zarr_tar(tmp_path: Path, seed: int = 0) -> Path:
    """Build a tar.gz mirroring a Ray run: seed_NN/store.zarr with an experiment_id=* partition.

    Note: xarray/numpy are not installed in the dashboard venv so we create the
    zarr directory structure manually.  _latest_zarr_for_study only requires the
    ``experiment_id=*`` child directory to exist (study_charts.py:641), not
    parseable zarr data, so a plain directory is sufficient for all test assertions.
    """
    staging = tmp_path / "staging"
    # Minimal store: the dashboard reader only needs the runs.*.zarr dir to contain an
    # experiment_id=* child to be selected; internal leaf detail is exercised elsewhere.
    part = staging / f"seed_{seed:02d}" / "store.zarr" / f"experiment_id=exp-seed{seed:02d}"
    part.mkdir(parents=True)
    # Place a sentinel file so the partition dir is non-empty (mirrors a real zarr shard)
    (part / ".zgroup").write_text('{"zarr_format":2}')
    tar_path = tmp_path / "sim_49.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(staging, arcname=".")
    return tar_path


def _make_remote_zarr_tar_multiseed(tmp_path: Path, seeds: tuple[int, ...] = (0, 1)) -> Path:
    """Build a tar.gz mirroring a real multi-seed Ray dispatch: one independently-rooted
    seed_NN/store.zarr per seed, each with its own uniquely-named experiment_id=* partition —
    exactly the shape confirmed against real GovCloud/Ray S3 output."""
    staging = tmp_path / "staging"
    for seed in seeds:
        part = staging / f"seed_{seed:02d}" / "store.zarr" / f"experiment_id=exp-seed{seed:02d}"
        part.mkdir(parents=True)
        (part / ".zgroup").write_text('{"zarr_format":2}')
        # Trivial top-level group marker, repeated per seed store (mirrors real output).
        (staging / f"seed_{seed:02d}" / "store.zarr" / "zarr.json").write_text('{"zarr_format":3}')
    tar_path = tmp_path / "sim_multiseed.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(staging, arcname=".")
    return tar_path


def _make_remote_zarr_tar_with_analysis(tmp_path: Path, seed: int = 0) -> Path:
    """A tar mirroring what lands once scripts/run_standalone_analysis.py (the
    v2ecoli-native standalone-analysis fix, v2ecoli#426/sms-ecoli#24) has
    completed: seed_NN/store.zarr plus an analyses/<name>/_manifest.json,
    written to the same S3 experiment prefix the download streams whole."""
    staging = tmp_path / "staging"
    part = staging / f"seed_{seed:02d}" / "store.zarr" / f"experiment_id=exp-seed{seed:02d}"
    part.mkdir(parents=True)
    (part / ".zgroup").write_text('{"zarr_format":2}')
    analysis_dir = staging / "analyses" / "analysis-exp-ab12"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "doubling_time_distribution.json").write_text(
        json.dumps({"n_cells": 2, "n_divided": 0, "final_dry_mass_mean": 220.0})
    )
    (analysis_dir / "_manifest.json").write_text(json.dumps({
        "analysis_name": "analysis-exp-ab12",
        "modules": {"multiseed": {"doubling_time_distribution": {}}},
        "written": ["s3://bucket/exp/analyses/analysis-exp-ab12/doubling_time_distribution.json"],
        "errors": [],
        "status": "done",
    }))
    tar_path = tmp_path / "sim_with_analysis.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(staging, arcname=".")
    return tar_path


def test_land_folds_analysis_manifest_into_pbg_runs_analyses_json(tmp_path: Path):
    """Once the analysis job has completed, landing (with ws_root passed) must
    fold its manifest into .pbg/runs/<run_id>/analyses.json -- the exact local
    artifact contract composite_flush.run_flush's own (non-remote) analyses
    dispatch already produces, so the existing Analyses button renders it with
    no further changes."""
    ws_root = tmp_path / "workspace"
    study = ws_root / "studies" / "s"
    study.mkdir(parents=True)
    tar = _make_remote_zarr_tar_with_analysis(tmp_path)

    run_id = land_remote_run(
        study, spec_id="s", simulation_id=115, experiment_id="e", commit="c",
        tar_path=tar, ws_root=ws_root,
    )

    analyses_path = ws_root / ".pbg" / "runs" / run_id / "analyses.json"
    assert analyses_path.is_file()
    entries = json.loads(analyses_path.read_text())
    assert entries == [{
        "name": "analysis-exp-ab12",
        "written": ["s3://bucket/exp/analyses/analysis-exp-ab12/doubling_time_distribution.json"],
        "errors": [],
    }]


def test_land_without_analysis_manifest_writes_nothing(tmp_path: Path):
    """If the analysis job hasn't completed by the time this run lands, landing
    the simulation output must still succeed -- and must not fabricate an
    analyses.json for output that was never actually produced."""
    ws_root = tmp_path / "workspace"
    study = ws_root / "studies" / "s"
    study.mkdir(parents=True)
    tar = _make_remote_zarr_tar(tmp_path)

    run_id = land_remote_run(
        study, spec_id="s", simulation_id=116, experiment_id="e", commit="c",
        tar_path=tar, ws_root=ws_root,
    )

    assert not (ws_root / ".pbg" / "runs" / run_id / "analyses.json").exists()


def test_land_without_ws_root_skips_analysis_folding(tmp_path: Path):
    """ws_root is optional -- existing callers that never trigger analysis for
    a landed run must be unaffected, even if a manifest happens to be present."""
    study = tmp_path / "study"
    study.mkdir()
    tar = _make_remote_zarr_tar_with_analysis(tmp_path)

    run_id = land_remote_run(
        study, spec_id="s", simulation_id=117, experiment_id="e", commit="c", tar_path=tar,
    )

    assert run_id  # lands normally; no ws_root means no .pbg/runs/ write attempted


def test_land_zarr_places_store_and_writes_runs_meta(tmp_path: Path):
    study = tmp_path / "study"
    study.mkdir()
    tar = _make_remote_zarr_tar(tmp_path)
    run_id = land_remote_run(
        study,
        spec_id="v2ecoli.composites.baseline",
        simulation_id=49,
        experiment_id="exp-abc",
        commit="abc123",
        tar_path=tar,
    )
    # zarr store placed at <study>/runs.<run_id>.zarr with the experiment_id=* partition intact
    zarr_dir = study / f"runs.{run_id}.zarr"
    assert zarr_dir.is_dir()
    assert next(zarr_dir.glob("experiment_id=*"), None) is not None

    # runs_meta written, status completed, provenance carries simulation_id, store path recorded
    conn = sqlite3.connect(str(study / "runs.db"))
    try:
        meta = conn.execute(
            "SELECT status, params_json FROM runs_meta WHERE run_id=?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    assert meta[0] == "completed"
    prov = json.loads(meta[1])
    assert prov["simulation_id"] == 49
    assert prov["store_path"].endswith(f"runs.{run_id}.zarr")


def test_landed_zarr_is_discovered_by_study_charts(tmp_path: Path):
    from vivarium_workbench.lib import study_charts

    study = tmp_path / "study"
    study.mkdir()
    tar = _make_remote_zarr_tar(tmp_path)
    run_id = land_remote_run(
        study, spec_id="s", simulation_id=7, experiment_id="e", commit="c", tar_path=tar
    )
    found = study_charts._latest_zarr_for_study(study)
    assert found == study / f"runs.{run_id}.zarr"


def test_land_stores_s3_uri_in_provenance(tmp_path: Path):
    """s3_uri kwarg is recorded in params_json provenance."""
    study = tmp_path / "study"
    study.mkdir()
    tar = _make_remote_zarr_tar(tmp_path)
    run_id = land_remote_run(
        study,
        spec_id="v2ecoli.composites.baseline",
        simulation_id=77,
        experiment_id="exp-s3",
        commit="deadbeef",
        tar_path=tar,
        s3_uri="s3://bucket/prefix/exp/",
    )
    conn = sqlite3.connect(str(study / "runs.db"))
    try:
        meta = conn.execute(
            "SELECT params_json FROM runs_meta WHERE run_id=?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    prov = json.loads(meta[0])
    assert prov["s3_uri"] == "s3://bucket/prefix/exp/"


def test_land_multiseed_keeps_every_seed(tmp_path: Path):
    """Regression: landing a 2-seed dispatch must keep BOTH seeds' partitions, not
    silently discard every seed but the first (the found bug — land_remote_run's
    seed param defaulted to 0 and no caller ever overrode it)."""
    study = tmp_path / "study"
    study.mkdir()
    tar = _make_remote_zarr_tar_multiseed(tmp_path, seeds=(0, 1))
    run_id = land_remote_run(
        study,
        spec_id="v2ecoli.composites.batch_baseline",
        simulation_id=114,
        experiment_id="exp-multiseed",
        commit="43cabf0",
        tar_path=tar,
    )
    zarr_dir = study / f"runs.{run_id}.zarr"
    partitions = sorted(p.name for p in zarr_dir.glob("experiment_id=*"))
    assert partitions == ["experiment_id=exp-seed00", "experiment_id=exp-seed01"]


def test_land_multiseed_single_seed_still_works(tmp_path: Path):
    """A single-seed dispatch (the common case) still lands correctly under the
    new union-all-seeds logic — no regression for the 1-seed path."""
    study = tmp_path / "study"
    study.mkdir()
    tar = _make_remote_zarr_tar_multiseed(tmp_path, seeds=(0,))
    run_id = land_remote_run(
        study, spec_id="s", simulation_id=1, experiment_id="e", commit="c", tar_path=tar,
    )
    zarr_dir = study / f"runs.{run_id}.zarr"
    assert [p.name for p in zarr_dir.glob("experiment_id=*")] == ["experiment_id=exp-seed00"]

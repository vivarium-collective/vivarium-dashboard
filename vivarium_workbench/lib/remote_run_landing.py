"""Land a remote simulation's NATIVE store into a study's run directory.

Mirror-the-store-format: extract the run's `/data` tar.gz and place the native
store unmodified where the dashboard's native chart reader expects it
(`<study>/runs.<run_id>.zarr` for zarr; `<study>/parquet-runs/<experiment_id>/`
for parquet), then record a runs_meta row. No reconstruction of leaf data — a
remote `seed_NN/store.zarr` is internally identical to the dashboard's expected
`runs.<run_id>.zarr`; only the path differs.

A multi-seed dispatch ships ONE `seed_NN/store.zarr` per seed in the same tar,
each independently rooted (confirmed against real GovCloud/Ray output: every
seed writes its own top-level zarr group). Landing merges every seed found
into the same destination root — each seed's `experiment_id=*-seedNN`
partition is already uniquely named per seed, so this is a plain union of
children, not a data merge.
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
import time as _time
from pathlib import Path

from vivarium_workbench.lib import composite_runs as cr


def _detect_and_locate_all(extract_root: Path) -> tuple[str, list[Path]]:
    """Find every native store under an extracted tar. Returns (kind, source_paths):
    one entry per seed for zarr, or a single entry for parquet."""
    seed_stores = sorted(extract_root.glob("**/seed_*/store.zarr"))
    if seed_stores:
        return "zarr", [s for s in seed_stores if s.is_dir()]
    # parquet: locate the experiment dir that contains a history/ subtree of .pq files
    pq = next(extract_root.glob("**/history/**/*.pq"), None)
    if pq is not None:
        # the experiment root is the parent of the `history` dir
        for parent in pq.parents:
            if parent.name == "history":
                return "parquet", [parent.parent]
    raise FileNotFoundError(f"no zarr (seed_NN/store.zarr) or parquet (history/**/*.pq) store in {extract_root}")


def land_remote_run(
    study_dir: Path,
    *,
    spec_id: str,
    simulation_id: int,
    experiment_id: str,
    commit: str,
    tar_path: Path,
    label: str | None = None,
    s3_uri: str | None = None,
) -> str:
    """Extract tar_path, place the native store(s) in study_dir, record runs_meta; return run_id."""
    study_dir = Path(study_dir)
    study_dir.mkdir(parents=True, exist_ok=True)

    from vivarium_workbench.lib.remote_pinned import remote_deployment_name
    deployment = remote_deployment_name()

    provenance = {
        "simulation_id": simulation_id,
        "experiment_id": experiment_id,
        "commit": commit,
        "backend": "ray",
        "source": deployment,
        "s3_uri": s3_uri,
    }
    run_id = cr.generate_run_id(spec_id, params=provenance)

    with tempfile.TemporaryDirectory() as td:
        extract_root = Path(td)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(extract_root, filter="data")  # noqa: S202 — trusted internal artifact from our own API
        kind, sources = _detect_and_locate_all(extract_root)
        if kind == "zarr":
            dest = study_dir / f"runs.{run_id}.zarr"
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            # Union every seed's children into one root. Each seed's
            # experiment_id=*-seedNN partition is already uniquely named, so this
            # never overwrites real data — only the trivial top-level zarr group
            # marker repeats across seeds, and the first one wins.
            for src in sources:
                for child in src.iterdir():
                    target = dest / child.name
                    if target.exists():
                        continue
                    if child.is_dir():
                        shutil.copytree(child, target)
                    else:
                        shutil.copy2(child, target)
        else:
            dest = study_dir / "parquet-runs" / experiment_id
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(sources[0], dest)

    provenance["store_path"] = str(dest)
    started = _time.time()
    conn = cr.connect(study_dir / "runs.db")
    try:
        cr.save_metadata(
            conn,
            spec_id=spec_id,
            run_id=run_id,
            params=provenance,
            label=label or f"Remote run ({deployment})",
            started_at=started,
            n_steps=0,
        )
        cr.complete_metadata(conn, run_id=run_id, n_steps=0, status="completed")
    finally:
        conn.close()

    return run_id

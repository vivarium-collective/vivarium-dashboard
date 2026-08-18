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
partition is already uniquely named per seed, so a plain union of top-level
children is safe there.

A second, DIFFERENT zarr convention is also landed here: BatchBaselineRunner /
LineageProcess's own native per-lineage store, named
`<experiment_id>_v<variant>_s<seed>.zarr` at the filesystem level (see
v2ecoli.steps.batch_baseline_runner._lineage_store_path) — the real shape a
batch produces when dispatched through the generic run_pbg.py runner (backlog
items 26/27), since that path never restructures its own output the way
scripts/run_batch_baseline_ray.py used to. Unlike the seed_NN convention,
EVERY lineage in one batch shares the SAME experiment_id, so uniqueness only
appears two levels inside each store (`experiment_id=X/variant=Y/lineage_seed=Z`
— confirmed against a real fixture, `pbg_emitters`' XArrayEmitter always nests
this 3-level partition path). A plain top-level union would keep only the
first-processed lineage and silently drop every other seed's data — the exact
shape of bug #674, recurring one convention later. `_merge_zarr_tree` recurses
past whatever depth a collision actually occurs at, so both conventions land
correctly through the same merge logic without hardcoding either one's depth.
"""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import time as _time
from pathlib import Path

from vivarium_workbench.lib import composite_runs as cr


def _fold_analyses(extract_root: Path, ws_root: Path, run_id: str) -> None:
    """Fold any standalone-analysis output already present in the landed tar into
    ``.pbg/runs/<run_id>/analyses.json`` -- the same local artifact contract
    composite_flush.run_flush's local (non-remote) analyses dispatch already
    produces, so the existing Analyses button needs no changes to render it.

    There is no status/poll endpoint for the K8s analysis job (see
    SmsApiClient.run_analysis), so completion is detected the same way the rest
    of this pipeline detects it: by finding the output already landed, here,
    rather than by polling sms-api. If the job hasn't finished by the time this
    run is landed, this is a no-op -- landing again later (once the analysis
    has actually completed) will pick it up.
    """
    manifests = sorted(extract_root.glob("**/analyses/*/_manifest.json"))
    if not manifests:
        return
    from vivarium_workbench.lib.workspace_paths import WorkspacePaths

    entries = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries.append({
            "name": manifest.get("analysis_name"),
            "written": manifest.get("written", []),
            "errors": manifest.get("errors", []),
        })
    run_dir = WorkspacePaths.load(ws_root).pbg / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "analyses.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _detect_and_locate_all(extract_root: Path) -> tuple[str, list[Path]]:
    """Find every native store under an extracted tar. Returns (kind, source_paths):
    one entry per lineage/seed for zarr, or a single entry for parquet.

    Two zarr layouts are recognized (see module docstring): the restructured
    `seed_NN/store.zarr` shape, and BatchBaselineRunner/LineageProcess's own
    native per-lineage naming (`<experiment_id>_v<variant>_s<seed>.zarr`).
    """
    seed_stores = sorted(extract_root.glob("**/seed_*/store.zarr"))
    if seed_stores:
        return "zarr", [s for s in seed_stores if s.is_dir()]
    native_stores = sorted(p for p in extract_root.glob("**/*_v*_s*.zarr") if p.is_dir())
    if native_stores:
        return "zarr", native_stores
    # parquet: locate the experiment dir that contains a history/ subtree of .pq files
    pq = next(extract_root.glob("**/history/**/*.pq"), None)
    if pq is not None:
        # the experiment root is the parent of the `history` dir
        for parent in pq.parents:
            if parent.name == "history":
                return "parquet", [parent.parent]
    raise FileNotFoundError(
        "no zarr (seed_NN/store.zarr or <experiment_id>_v<variant>_s<seed>.zarr) "
        f"or parquet (history/**/*.pq) store in {extract_root}"
    )


def _merge_zarr_tree(src: Path, dest: Path) -> None:
    """Merge src's children into dest, recursing into a name collision instead of
    skipping it outright.

    The fast path (no collision) is an untouched bulk `shutil.copytree`/`copy2` —
    identical to the old shallow union, and what every level of the seed_NN/store.zarr
    convention always takes, since its top-level partition names never collide across
    seeds. A collision only arises for a convention whose uniqueness lives deeper than
    the top level (the native per-lineage store's shared `experiment_id=X/variant=Y`
    prefix — see module docstring) — recursing past it, rather than skipping the whole
    subtree, is what actually merges every lineage's data instead of keeping only the
    first one processed. A genuine leaf-level collision (both sides are the SAME file,
    e.g. the trivial shared zarr group marker) is left as first-wins, matching a745f899.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dest / child.name
        if not target.exists():
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)
        elif child.is_dir() and target.is_dir():
            _merge_zarr_tree(child, target)
        # else: both exist and at least one is a file -- dest's version wins.


def land_remote_run(
    study_dir: Path,
    *,
    spec_id: str,
    simulation_id: int,
    experiment_id: str,
    commit: str,
    tar_path: Path,
    ws_root: Path | None = None,
    label: str | None = None,
    s3_uri: str | None = None,
) -> str:
    """Extract tar_path, place the native store(s) in study_dir, record runs_meta; return run_id.

    ``ws_root`` is optional (defaults to no analyses-folding) so existing callers
    that only land simulation output, with no analysis ever triggered for that
    run, are unaffected.
    """
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
            # Merge every seed/lineage's store into one root -- see _merge_zarr_tree
            # for why this recurses into collisions rather than skipping them.
            for src in sources:
                _merge_zarr_tree(src, dest)
        else:
            dest = study_dir / "parquet-runs" / experiment_id
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(sources[0], dest)

        if ws_root is not None:
            _fold_analyses(extract_root, ws_root, run_id)

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
            # Pass the workspace so save_metadata auto-stamps a source-provenance
            # manifest (repo + commit of the local checkout that landed this
            # remote run) — otherwise the Runs table's Source column is blank
            # for every remote/GovCloud run. (The row's remote_origin still comes
            # from `provenance` (source/simulation_id); this only adds the
            # manifest's code_version.)
            workspace=ws_root,
        )
        cr.complete_metadata(conn, run_id=run_id, n_steps=0, status="completed")
    finally:
        conn.close()

    return run_id

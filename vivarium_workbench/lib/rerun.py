"""Rerun a recorded/declared run at investigation / study / simulation level.
Thin orchestration over the run subsystem; never overwrites — always a new run."""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib import cli_runs
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def resolve_rerun_target(ws_root, run_id):
    db_file, row = cli_runs.find_run(ws_root, run_id)
    if row is None:
        return None
    dbp = Path(db_file)
    wp = WorkspacePaths.load(Path(ws_root))
    studies_root = Path(wp.studies).resolve()
    origin, study = "composite", None
    # study runs.db lives at <studies_root>/<slug>/runs.db
    if dbp.name == "runs.db" and dbp.parent.parent.resolve() == studies_root:
        origin, study = "study", dbp.parent.name
    return {
        "run_id": run_id, "origin": origin, "study": study,
        "spec_id": row.get("spec_id"),
        "params": dict(row.get("params") or {}),
        "n_steps": int(row.get("n_steps") or 5),
    }

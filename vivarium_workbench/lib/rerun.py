"""Rerun a recorded/declared run at investigation / study / simulation level.
Thin orchestration over the run subsystem; never overwrites — always a new run."""
from __future__ import annotations

import json
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

    # Prefer the full replay manifest (Task 2) when present — it carries the
    # FULL effective params (not the delta) plus emitter/emit_paths/runtime,
    # so a rerun reproduces exactly what this run used instead of whatever
    # study.yaml/workspace.yaml currently say. Legacy runs (no manifest) fall
    # back to the delta params_json/n_steps below.
    manifest = None
    manifest_json = row.get("manifest_json")
    if manifest_json:
        try:
            manifest = json.loads(manifest_json)
        except (json.JSONDecodeError, TypeError):
            manifest = None

    if manifest:
        return {
            "run_id": run_id,
            "origin": manifest.get("origin") or origin,
            "study": manifest.get("study") if manifest.get("study") is not None else study,
            "spec_id": manifest.get("spec_id") or row.get("spec_id"),
            "params": dict(manifest.get("params") or {}),
            "n_steps": int(manifest.get("n_steps") or row.get("n_steps") or 5),
            "emitter": manifest.get("emitter"),
            "emit_paths": manifest.get("emit_paths"),
            "runtime": manifest.get("runtime"),
        }

    return {
        "run_id": run_id, "origin": origin, "study": study,
        "spec_id": row.get("spec_id"),
        "params": dict(row.get("params") or {}),
        "n_steps": int(row.get("n_steps") or 5),
        # Uniform shape with the manifest branch above; legacy runs simply
        # have no recorded emitter/emit_paths/runtime to replay.
        "emitter": None, "emit_paths": None, "runtime": None,
    }

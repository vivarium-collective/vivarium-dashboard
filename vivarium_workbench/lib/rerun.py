"""Rerun a recorded/declared run at investigation / study / simulation level.
Thin orchestration over the run subsystem; never overwrites — always a new run."""
from __future__ import annotations

import json
from pathlib import Path

from vivarium_workbench.lib import cli_runs, study_runs
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
        params = dict(manifest.get("params") or {})
        # n_steps must not leak into the replayed generator params: the
        # ORIGINAL run (study_runs.run_study_baseline) pops n_steps out of
        # params before building the generator config, so the manifest's
        # params (built from full_params = {**params, "n_steps": n_steps})
        # carries it back in. Strip it here and keep it only in its own
        # field so the replayed config matches the original run's config.
        n_steps = int(params.pop("n_steps", None) or manifest.get("n_steps") or row.get("n_steps") or 5)
        return {
            "run_id": run_id,
            "origin": manifest.get("origin") or origin,
            "study": manifest.get("study") if manifest.get("study") is not None else study,
            "spec_id": manifest.get("spec_id") or row.get("spec_id"),
            "params": params,
            "n_steps": n_steps,
            "emitter": manifest.get("emitter"),
            "emit_paths": manifest.get("emit_paths"),
            "runtime": manifest.get("runtime"),
        }

    params = dict(row.get("params") or {})
    n_steps = int(params.pop("n_steps", None) or row.get("n_steps") or 5)
    return {
        "run_id": run_id, "origin": origin, "study": study,
        "spec_id": row.get("spec_id"),
        "params": params,
        "n_steps": n_steps,
        # Uniform shape with the manifest branch above; legacy runs simply
        # have no recorded emitter/emit_paths/runtime to replay.
        "emitter": None, "emit_paths": None, "runtime": None,
    }


def run_rerun(ws_root, run_id):
    """Replay a recorded run as a brand-new run, routed by its origin.

    Resolves the replay target (Task 2's ``resolve_rerun_target``, manifest-
    preferred) and forwards its inputs VERBATIM to the matching launcher —
    a study-origin run replays via ``study_runs.launch_into_study`` (full
    manifest: spec_id/params/n_steps/emitter/emit_paths/runtime), a
    composite-origin run replays via ``cli_runs.run_composite`` (detached
    subprocess). Never mutates the original run; always produces a new one.
    """
    t = resolve_rerun_target(ws_root, run_id)
    if t is None:
        return {"error": f"run not found: {run_id}"}, 404
    if t["origin"] == "study":
        resp, status = study_runs.launch_into_study(
            ws_root, t["study"], t["spec_id"], t["params"], t["n_steps"],
            emitter=t.get("emitter"), emit_paths=t.get("emit_paths"), runtime=t.get("runtime"))
    else:
        resp, status = cli_runs.run_composite(
            ws_root, t["spec_id"], steps=t["n_steps"], params=t["params"],
            emit_paths=t.get("emit_paths") or [], detach=True)
    if isinstance(resp, dict):
        resp = {**resp, "origin": t["origin"], "reran": run_id}
    return resp, status


def _investigation_studies(ws_root, investigation):
    """Return an investigation's declared member-study slugs.

    Reads ``investigations/<investigation>/investigation.yaml``'s
    ``studies:`` list directly (resolved via ``WorkspacePaths``) rather than
    ``investigations.load_spec`` — that loader is study-oriented (validates
    a *study* spec's schema), not the investigation-level ``studies:``
    roster. Mirrors ``run_unblocked_views.investigation_run_unblocked``'s
    member-name extraction: each entry is either a bare slug string or a
    dict with a ``study``/``name`` key. Missing file or empty list -> ``[]``.
    """
    import yaml

    wp = WorkspacePaths.load(Path(ws_root))
    inv_yaml = wp.investigations / str(investigation) / "investigation.yaml"
    if not inv_yaml.is_file():
        return []
    try:
        spec = yaml.safe_load(inv_yaml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(spec, dict):
        return []
    out = []
    for member in (spec.get("studies") or []):
        if isinstance(member, str):
            out.append(member)
        elif isinstance(member, dict):
            slug = member.get("study") or member.get("name")
            if slug:
                out.append(slug)
    return out


def rerun_investigation(ws_root, investigation):
    """Rerun every member study of an investigation's baseline (force).

    Iterates the investigation's declared studies and re-launches each
    one's baseline via ``study_runs.run_study_baseline`` (ignoring any
    unblocked-gate — this is an explicit rerun, not gated batch enumeration).
    One bad study's exception or non-2xx response is recorded in ``errors``
    rather than aborting the rest of the batch.
    """
    studies = _investigation_studies(ws_root, investigation)
    launched, errors = [], []
    for s in studies:
        try:
            resp, status = study_runs.run_study_baseline(ws_root, {"study": s})
        except Exception as e:  # noqa: BLE001 — one bad study must not abort the batch
            errors.append({"study": s, "error": str(e)})
            continue
        if status < 300 and (resp or {}).get("run_id"):
            launched.append({"study": s, "run_id": resp["run_id"]})
        else:
            errors.append({"study": s, "error": (resp or {}).get("error", status)})
    return {"investigation": investigation, "launched": launched, "errors": errors,
            "count": len(launched)}, 200

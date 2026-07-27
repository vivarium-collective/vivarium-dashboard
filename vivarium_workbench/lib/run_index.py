"""Retrieve-before-recompute over saved runs (reproducible-rerun-spine
Task 6 / G5, item 7 of the spine).

The user's explicit ask: "we hold onto simulation artifacts, like saved
runs, so if we have access to that we may not have to rerun older studies."
When a Reproduce (``rerun.run_rerun``) would recompute a run whose exact
replay key we ALREADY have a completed, intact, matching saved run for,
that saved artifact should be served instead of launching a new subprocess.

:func:`find_matching_run` is the read-only lookup this decision hinges on.
It reuses the existing ``composite_runs`` DB-access helpers (``connect``,
``query_runs``, ``query_run_meta``) rather than hand-rolling a new SQLite
connection pattern, and scans every ``runs_meta`` DB a workspace owns — the
workspace-level ``.pbg/composite-runs.db`` plus each study's
``studies/<slug>/runs.db`` (mirrors ``cli_runs.find_run``'s candidate list;
this function's signature carries no ``study`` parameter, so it cannot be
told in advance which DB to look in — it also does not need to be exact
about scope: the ``spec_id``/``env_id``/config/seed comparison below is
already so specific that a spec_id shared across two studies is a
harmless coincidence, not a correctness risk).

A match requires ALL of:
  - same ``spec_id``
  - ``status == 'completed'``
  - non-null ``result_fingerprint`` (Task 3 — a genuinely finished, hashed
    run, not merely "not failed yet")
  - same ``env_id`` as the caller's ``env_id`` argument. The caller is
    expected to pass the environment a NEW launch would be stamped with
    (i.e. ``env_fingerprint.env_id(env_fingerprint.compute_env(...))``
    computed fresh, the same convention ``rerun._flag_env_drift`` already
    uses) — so a drifted environment naturally fails to match ANY existing
    run, including the very run being reproduced.
  - the same canonical config (``n_steps``-stripped, manifest-preferred —
    the same normalization ``rerun.resolve_rerun_target`` applies to what
    it forwards to a replay) and the same seed (manifest-preferred, same
    fallback convention as ``rerun._row_seed``).
  - its on-disk artifact snapshot (``result_fingerprint.SNAPSHOT_FILENAME``
    under ``<ws>/.pbg/runs/<run_id>/``) still exists — a run whose output
    was deleted (e.g. via the Composite Explorer's "remove run") must never
    be "retrieved".

Best-effort throughout: a bad row, corrupt JSON, unreadable DB, or
filesystem error degrades to "no match" (never raises) — a lookup failure
here must fall through to a normal recompute, never crash a reproduce.
"""
from __future__ import annotations

import json
from pathlib import Path

from vivarium_workbench.lib import composite_runs as cr
from vivarium_workbench.lib import result_fingerprint as rfp
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _canonical(value) -> str:
    """Canonical JSON string for equality comparison — the same
    ``json.dumps(..., sort_keys=True)`` convention ``composite_runs.
    generate_run_id`` already hashes its own payload with."""
    return json.dumps(value or {}, sort_keys=True, default=str)


def _row_config(row: dict) -> dict:
    """This row's replay config, normalized the same way ``rerun.
    resolve_rerun_target`` normalizes what it forwards to a replay: prefer
    the full manifest ``params`` (n_steps popped back out — the manifest
    merges it in via ``full_params = {**params, "n_steps": n_steps}``),
    else fall back to the legacy ``params_json`` params (also n_steps-
    stripped) so pre- and post-manifest rows compare on the same basis."""
    manifest_json = row.get("manifest_json")
    manifest = None
    if manifest_json:
        try:
            manifest = json.loads(manifest_json)
        except (TypeError, json.JSONDecodeError):
            manifest = None
    params = dict((manifest or {}).get("params") or row.get("params") or {})
    params.pop("n_steps", None)
    return params


def _row_seed(row: dict):
    """This row's first-class replay seed — mirrors ``rerun._row_seed``:
    prefer the manifest's ``seed`` key, fall back to ``params["seed"]`` for
    a row whose manifest predates Task 4 (or has none at all)."""
    manifest_json = row.get("manifest_json")
    if manifest_json:
        try:
            manifest = json.loads(manifest_json)
        except (TypeError, json.JSONDecodeError):
            manifest = None
        if manifest and manifest.get("seed") is not None:
            return manifest.get("seed")
    return (row.get("params") or {}).get("seed")


def _artifact_intact(ws, run_id: str) -> bool:
    """True iff this run's canonical output snapshot — ``result_fingerprint
    .SNAPSHOT_FILENAME`` under ``<ws>/.pbg/runs/<run_id>/``, written at
    completion by both the study-origin (``composite_subprocess``) and
    composite-origin (``run_runner.execute``) run paths — is still on disk.

    This is the artifact retrieve-before-recompute would actually need to
    serve; a deleted run dir (e.g. the Composite Explorer's "remove run",
    ``simulations_index``'s ``run_dir`` rmtree) or a partial/missing
    snapshot both fail this check, so a stale DB row never gets "retrieved".
    """
    try:
        wp = WorkspacePaths.load(Path(ws))
        run_dir = wp.pbg / "runs" / str(run_id)
        return (run_dir / rfp.SNAPSHOT_FILENAME).is_file()
    except Exception:  # noqa: BLE001 — best-effort; missing -> no match
        return False


def _candidate_dbs(ws):
    """Every ``runs_meta`` DB this workspace owns — the workspace-level
    composite-runs.db plus each study's runs.db (mirrors ``cli_runs.
    find_run``'s candidate list)."""
    wp = WorkspacePaths.load(Path(ws))
    out = [wp.pbg / "composite-runs.db"]
    out.extend(sd / "runs.db" for sd in wp.iter_study_dirs())
    return out


def find_matching_run(ws, spec_id, config, seed, env_id):
    """Find an existing COMPLETED run matching (``spec_id``, ``config``,
    ``seed``, ``env_id``) whose on-disk artifact is still intact, so a
    Reproduce can serve it instead of recomputing. Returns the
    ``composite_runs.query_run_meta`` row dict, or ``None`` on no match (or
    any best-effort failure along the way).

    Ties (more than one matching completed run in the same DB): the most
    recently started one wins — ``query_runs`` already orders newest-first.
    """
    if not spec_id or not env_id:
        return None
    try:
        target_config = _canonical(config)
        for db_file in _candidate_dbs(ws):
            db_file = Path(db_file)
            if not db_file.is_file():
                continue
            try:
                conn = cr.connect(str(db_file))
            except Exception:  # noqa: BLE001 — unreadable/corrupt DB -> skip it
                continue
            try:
                for candidate in cr.query_runs(conn, spec_id=spec_id):
                    if candidate.get("status") != "completed":
                        continue
                    try:
                        row = cr.query_run_meta(conn, run_id=candidate["run_id"])
                    except Exception:  # noqa: BLE001 — bad row -> skip it
                        continue
                    if row is None:
                        continue
                    if row.get("env_id") != env_id:
                        continue
                    if not row.get("result_fingerprint"):
                        continue
                    if _canonical(_row_config(row)) != target_config:
                        continue
                    if _row_seed(row) != seed:
                        continue
                    if not _artifact_intact(ws, row["run_id"]):
                        continue
                    return row
            except Exception:  # noqa: BLE001 — best-effort; try the next DB
                continue
            finally:
                conn.close()
    except Exception:  # noqa: BLE001 — best-effort; a lookup failure is "no match"
        return None
    return None

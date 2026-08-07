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
connection pattern.

Scoping (review round 1, Finding 1): a match must come from the run's OWN
owning DB — a composite-origin run's is the workspace-level
``.pbg/composite-runs.db``; a study-origin run's is that specific study's
``studies/<slug>/runs.db``. Many studies share baseline composites with
identical default params/seed, so scanning every study's DB (the original
implementation) could return a completed, intact match recorded under a
DIFFERENT study — correct on paper (same spec_id/config/seed/env_id/
fingerprint) but confusing in practice: that run stays tagged to its
original study_slug, so the REPRODUCING study's own ``/api/simulations?
study=<slug>`` list and Simulations-tab never show it. ``find_matching_run``
therefore takes the caller's resolved ``origin``/``study`` (the same values
``rerun.resolve_rerun_target`` already computes) and looks ONLY in that
run's owning DB — never a sibling study's.

Shared match-key/replay-key derivation (review round 1, Finding 2):
:func:`row_seed` and :func:`replay_params` are the SINGLE source of truth
for "what does this row's manifest/params say the replay seed/config are" —
used by BOTH this module's ``find_matching_run`` (the match key a retrieve
decision hinges on) and ``rerun.resolve_rerun_target`` (the actual replay
inputs a compute-path launch forwards). Two independent copies of this
derivation could silently drift apart, so there is exactly one.

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
  - the same canonical config (:func:`replay_params`'s ``params`` half —
    n_steps-stripped, manifest-preferred, the SAME derivation
    ``rerun.resolve_rerun_target`` forwards to an actual replay) and the
    same seed (:func:`row_seed`).
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


def _parse_manifest(row: dict) -> "dict | None":
    """Best-effort ``manifest_json`` -> dict, or ``None`` when absent,
    corrupt, or not an object. Single parse point for :func:`row_seed` and
    :func:`replay_params`."""
    manifest_json = row.get("manifest_json")
    if not manifest_json:
        return None
    try:
        manifest = json.loads(manifest_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def row_seed(row: dict):
    """This row's first-class replay seed — THE single derivation shared by
    ``find_matching_run`` (match key) and ``rerun.resolve_rerun_target``
    (actual replay input), so the two can never silently disagree on what
    "the same seed" means. Prefers the manifest's ``seed`` key; falls back
    to ``params["seed"]`` for a row whose manifest predates Task 4 (or has
    none at all) — the convention ``build_run_manifest`` itself uses."""
    manifest = _parse_manifest(row)
    if manifest and manifest.get("seed") is not None:
        return manifest.get("seed")
    return (row.get("params") or {}).get("seed")


def replay_params(row: dict) -> "tuple[dict, int]":
    """This row's replay ``(params, n_steps)`` — THE single derivation
    shared by ``find_matching_run`` (match key's config half) and
    ``rerun.resolve_rerun_target`` (actual replay inputs a compute-path
    launch forwards), so a retrieve decision and a real replay can never
    silently compare/launch on different bases.

    Prefers the full manifest ``params`` (n_steps popped back OUT — the
    manifest merges it in via ``full_params = {**params, "n_steps":
    n_steps}``), else falls back to the legacy ``params_json`` params (also
    n_steps-stripped) so pre- and post-manifest rows are handled on the
    same basis. ``n_steps`` itself falls back to the manifest's own
    ``n_steps`` field, then the row's ``n_steps`` column, then ``5``
    (mirrors the exact fallback chain ``resolve_rerun_target`` used before
    this derivation was factored out)."""
    manifest = _parse_manifest(row)
    if manifest:
        params = dict(manifest.get("params") or {})
        n_steps = params.pop("n_steps", None) or manifest.get("n_steps") or row.get("n_steps") or 5
        return params, int(n_steps)
    params = dict(row.get("params") or {})
    n_steps = params.pop("n_steps", None) or row.get("n_steps") or 5
    return params, int(n_steps)


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


def _owning_db(ws, origin: "str | None", study: "str | None") -> "Path | None":
    """The single ``runs_meta`` DB that OWNS a run of this origin (review
    round 1, Finding 1) — a study-origin run's own ``studies/<slug>/
    runs.db``, or the workspace-level ``.pbg/composite-runs.db`` for a
    composite-origin run. Returns ``None`` when the origin can't be
    resolved to exactly one DB (unrecognized origin, or a study-origin run
    with no/unresolvable study), so the caller degrades to "no match"
    rather than guessing (and never falls back to scanning every DB — that
    was the bug: a sibling study's identically-configured baseline run
    could get "retrieved" under a study it does not belong to)."""
    wp = WorkspacePaths.load(Path(ws))
    if origin == "study":
        if not study:
            return None
        try:
            return wp.study_dir(str(study), must_exist=True) / "runs.db"
        except FileNotFoundError:
            return None
    if origin == "composite":
        return wp.pbg / "composite-runs.db"
    return None


def find_matching_run(ws, spec_id, config, seed, env_id, *, origin, study=None):
    """Find an existing COMPLETED run matching (``spec_id``, ``config``,
    ``seed``, ``env_id``) whose on-disk artifact is still intact, so a
    Reproduce can serve it instead of recomputing. Returns the
    ``composite_runs.query_run_meta`` row dict, or ``None`` on no match (or
    any best-effort failure along the way).

    ``origin``/``study`` (keyword-only, required) scope the lookup to the
    run's OWN owning DB (review round 1, Finding 1) — the same values
    ``rerun.resolve_rerun_target`` already resolves for the run being
    reproduced. A match is NEVER drawn from a different study's (or the
    workspace's, for a study-origin lookup) DB, even if its spec_id/config/
    seed/env_id happen to coincide.

    Ties (more than one matching completed run in the owning DB): the most
    recently started one wins — ``query_runs`` already orders newest-first.
    """
    if not spec_id or not env_id:
        return None
    db_file = _owning_db(ws, origin, study)
    if db_file is None or not Path(db_file).is_file():
        return None
    try:
        target_config = _canonical(config)
        try:
            conn = cr.connect(str(db_file))
        except Exception:  # noqa: BLE001 — unreadable/corrupt DB -> no match
            return None
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
                row_params, _row_n_steps = replay_params(row)
                if _canonical(row_params) != target_config:
                    continue
                if row_seed(row) != seed:
                    continue
                if not _artifact_intact(ws, row["run_id"]):
                    continue
                return row
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — best-effort; a lookup failure is "no match"
        return None
    return None

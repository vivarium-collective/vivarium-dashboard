"""Deterministic pull-or-compute pipeline resolver.

``resolve_study`` recurses into a study's declared input producers first —
each producer's own ``resolve_study`` call IS the pull-or-compute for that
producer, so a store hit there means no recompute — then resolves this
study's own output artifact, keyed by ``(composite, config, resolved input
ids, workspace commit)`` via ``hashing.artifact_id``. A matching id already in
the ``ArtifactStore`` is pulled (no compute); otherwise ``compute_fn`` (or the
best-effort real-engine adapter, ``_default_compute``) is called exactly once
to produce it, and the result is stored.

Hard constraint: NO ``datetime.now()`` / RNG / wall-clock anywhere in this
file. The whole point of content-addressing is that identical inputs always
resolve to the identical artifact id, so the resolve path must be pure with
respect to everything except the artifact store's on-disk contents.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

import yaml

from vivarium_workbench.lib.artifacts.hashing import artifact_id
from vivarium_workbench.lib.artifacts.store import ArtifactStore
from vivarium_workbench.lib.study_spec import study_interface
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _workspace_commit(ws_root) -> str:
    """Current git HEAD of the workspace, or "" when not a git checkout.

    A tmp/non-git workspace (as used by the unit tests) always yields ""
    within a given test — deterministic, not wall-clock-derived.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["git", "-C", str(ws_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _load_study_spec(ws_root: Path, slug: str) -> dict:
    """Load ``studies/<slug>/study.yaml`` (nested-first via WorkspacePaths).

    Mirrors the resolution pattern in
    ``investigation_graph_views.build_investigation_graph``: resolve the
    study dir through ``WorkspacePaths.study_dir`` (which raises
    ``FileNotFoundError`` for an unknown slug — left to propagate, since an
    unresolvable input producer is an authoring error the resolver should
    surface, not swallow).
    """
    wp = WorkspacePaths.load(ws_root)
    spec_path = wp.study_dir(slug) / "study.yaml"
    return yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}


def _record_pointer(runs_db: Path, stage: str, oid: str) -> None:
    """Upsert ``(stage, artifact_id)`` into ``runs.db``'s ``artifact_pointers``.

    Additive table only — never touches any existing runs.db table/schema.
    Best-effort: a locked or otherwise misbehaving db must never crash a
    resolve, so any failure here is swallowed.
    """
    try:
        conn = sqlite3.connect(str(runs_db))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS artifact_pointers ("
                "stage TEXT PRIMARY KEY, artifact_id TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO artifact_pointers (stage, artifact_id) "
                "VALUES (?, ?) "
                "ON CONFLICT(stage) DO UPDATE SET artifact_id=excluded.artifact_id",
                (stage, oid),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — pointer bookkeeping is best-effort
        pass


def resolve_study(ws_root, slug: str, *, compute_fn=None) -> dict:
    """Pull-or-compute this study's output artifact, recursing into input
    producers first.

    Returns:
      {
        "slug": slug,
        "output": <str>,          # output artifact name = interface.outputs[0] if present else slug
        "artifact_id": <str>,     # 16-char id of THIS study's output artifact
        "cached": <bool>,         # True => store already had it (compute_fn NOT called for this study)
        "inputs": { <from_slug>: <input_artifact_id>, ... },  # resolved producer output ids
      }
    """
    ws_root = Path(ws_root)
    wp = WorkspacePaths.load(ws_root)
    spec = _load_study_spec(ws_root, slug)
    iface = study_interface(spec)
    output_name = iface["outputs"][0] if iface["outputs"] else slug

    # Resolve inputs first — recursion IS the pull-or-compute for producers.
    inputs_map: dict[str, str] = {}
    for inp in iface["inputs"]:
        child = resolve_study(ws_root, inp["from"], compute_fn=compute_fn)
        inputs_map[inp["from"]] = child["artifact_id"]

    commit = _workspace_commit(ws_root)
    oid = artifact_id(
        composite_id=iface["composite"] or slug,
        config=iface["config"],
        input_ids=sorted(inputs_map.values()),
        commit=commit,
    )

    store = ArtifactStore(ws_root)
    if store.has(oid):
        cached = True
    else:
        cached = False
        # Each compute attempt gets its OWN unique scratch dir (never just
        # `oid`) so two concurrent resolves that both miss the same `oid`
        # (e.g. two dependents of the same producer, or a double-clicked
        # rerun in the request-serving dashboard) can't stomp each other —
        # a shared `oid`-named dir would let one writer's pre-compute
        # `rmtree` delete another writer's in-flight scratch mid-compute.
        # The dir name is transient filesystem isolation only: it never
        # enters `artifact_id` and never affects stored content, so this
        # stays fully deterministic — `store.put` is idempotent, so if two
        # attempts race, the first to `put` wins and the second is a no-op
        # store hit.
        scratch_root = wp.pbg / "_scratch"
        scratch_root.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=f"{oid}-", dir=scratch_root))
        try:
            fn = compute_fn or _default_compute
            produced = fn(
                ws_root, slug,
                artifact_id=oid,
                composite=iface["composite"],
                config=iface["config"],
                input_ids=sorted(inputs_map.values()),
                out_dir=scratch,
            )
            store.put(oid, produced, {"slug": slug, "stage": output_name})
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    _record_pointer(wp.study_dir(slug) / "runs.db", output_name, oid)

    return {
        "slug": slug,
        "output": output_name,
        "artifact_id": oid,
        "cached": cached,
        "inputs": inputs_map,
    }


def _default_compute(ws_root, slug, *, artifact_id, composite, config, input_ids, out_dir):
    """Real-engine adapter (Spec-1 Global Constraint: reuse run_core.invoke_run /
    run_runner.execute — do NOT reimplement running). This seam is exercised
    end-to-end in Task 8; Task 5's unit tests inject a stub compute_fn instead.

    Best-effort wiring: build a run-request the same shape
    ``run_runner.RunRequest.from_file`` expects, invoke ``run_core.invoke_run``
    to plan it, then hand it to ``run_runner.execute`` to actually run, and
    return ``out_dir`` (which now also holds the run's ``runs.db`` + log +
    any rendered viz) as the artifact payload. Imports are lazy so importing
    this module never pulls in the run subsystem, and unit tests (which
    always inject their own ``compute_fn``) never exercise this path.
    """
    import json

    from vivarium_workbench.lib import run_core
    from vivarium_workbench.lib import run_runner

    ws_root = Path(ws_root)
    wp = WorkspacePaths.load(ws_root)
    out_dir = Path(out_dir)
    db_path = out_dir / "runs.db"

    plan = run_core.invoke_run(
        ws_root, spec_id=composite or slug, config=config, db_path=db_path,
    )

    # NOTE (Task 8 integration): the run-request shape below is the best
    # inference available from run_runner.RunRequest — n_steps/emit_paths
    # aren't part of the pipeline `interface` contract yet, so `steps`
    # defaults from config (or a placeholder) and `emit_paths` is left
    # empty pending however Task 8 wires a study's declared outputs to
    # emitter paths.
    request = {
        "run_id": plan.run_id,
        "spec_id": plan.spec_id,
        "pkg": wp.package.name,
        "workspace": str(ws_root),
        "overrides": config or {},
        "steps": int((config or {}).get("n_steps") or 1),
        "emit_paths": [],
        "db_file": str(db_path),
        "log_path": str(out_dir / "run.log"),
        "target": plan.target,
    }
    request_path = out_dir / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    run_runner.execute(request_path)
    return out_dir

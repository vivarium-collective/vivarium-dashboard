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

import graphlib
import shutil
import sqlite3
import tempfile
from pathlib import Path

import yaml

from vivarium_workbench.lib.artifacts.hashing import artifact_id
from vivarium_workbench.lib.artifacts.store import ArtifactStore
from vivarium_workbench.lib.composite_runs import collect_emit_paths_from_spec
from vivarium_workbench.lib.investigation_members import investigation_member_slugs
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


class CyclicDependencyError(Exception):
    """Raised when a study's ``inputs[].from`` chain cycles back on itself."""


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


def _load_investigation_spec(ws_root: Path, inv_slug: str) -> dict:
    """Load ``investigations/<inv_slug>/investigation.yaml``.

    Split out as its own (monkeypatchable) seam — mirrors ``_load_study_spec``
    — so ``resolve_investigation`` tests can fake an investigation's member
    list without needing a real ``investigations/`` dir on disk.
    """
    wp = WorkspacePaths.load(ws_root)
    spec_path = wp.investigations / inv_slug / "investigation.yaml"
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


def resolve_study(
    ws_root, slug: str, *, compute_fn=None, force: bool = False, _in_progress=None,
) -> dict:
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

    Args:
      force: when True, bypass the ``store.has(oid)`` short-circuit for THIS
        study (compute_fn always runs; ``cached`` is reported False). Does
        NOT propagate to producer resolution — a caller that wants a whole
        subtree forced (e.g. ``resolve_investigation``) resolves every node
        explicitly with ``force=True`` in topological order, so a producer
        is already force-recomputed by the time a dependent's internal
        recursive call reads it back (a cheap store hit on the same oid).

    Raises:
      CyclicDependencyError: a study's ``inputs[].from`` chain re-enters a
        slug already on the current recursion stack (e.g. a -> b -> a).
        ``_in_progress`` is the private threading mechanism for that guard —
        callers should never pass it themselves.
    """
    in_progress = set() if _in_progress is None else _in_progress
    if slug in in_progress:
        raise CyclicDependencyError(" -> ".join([*in_progress, slug]))
    in_progress.add(slug)
    try:
        ws_root = Path(ws_root)
        wp = WorkspacePaths.load(ws_root)
        spec = _load_study_spec(ws_root, slug)
        iface = study_interface(spec)
        output_name = iface["outputs"][0] if iface["outputs"] else slug

        # Resolve inputs first — recursion IS the pull-or-compute for producers.
        inputs_map: dict[str, str] = {}
        for inp in iface["inputs"]:
            child = resolve_study(
                ws_root, inp["from"], compute_fn=compute_fn, _in_progress=in_progress,
            )
            inputs_map[inp["from"]] = child["artifact_id"]

        commit = _workspace_commit(ws_root)
        oid = artifact_id(
            composite_id=iface["composite"] or slug,
            config=iface["config"],
            input_ids=sorted(inputs_map.values()),
            commit=commit,
        )

        store = ArtifactStore(ws_root)
        if not force and store.has(oid):
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
            # stays fully deterministic — `store.put` is idempotent by default,
            # so if two attempts race, the first to `put` wins and the second
            # is a no-op store hit (force=True passes overwrite=True below,
            # which trades that race-safety for actually refreshing a forced
            # recompute's content instead of discarding it).
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
                store.put(oid, produced, {"slug": slug, "stage": output_name}, overwrite=force)
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
    finally:
        in_progress.discard(slug)


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

    # Load study spec and collect emit_paths from declared observables
    # (readouts, tests, visualizations, etc). Fall back to [] only when
    # the study declares no observables (run_runner then expands [] to all-store).
    spec = _load_study_spec(ws_root, slug)
    emit_paths = collect_emit_paths_from_spec(spec) or []

    # NOTE (Task 8 integration): the run-request shape below is the best
    # inference available from run_runner.RunRequest — n_steps/emit_paths
    # are now wired from the study spec (Task 4), so `steps` defaults
    # from config (or a placeholder) and `emit_paths` is collected above.
    request = {
        "run_id": plan.run_id,
        "spec_id": plan.spec_id,
        "pkg": wp.package.name,
        "workspace": str(ws_root),
        "overrides": config or {},
        "steps": int((config or {}).get("n_steps") or 1),
        "emit_paths": emit_paths,
        "db_file": str(db_path),
        "log_path": str(out_dir / "run.log"),
        "target": plan.target,
    }
    request_path = out_dir / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    run_runner.execute(request_path)
    return out_dir


def resolve_investigation(
    ws_root, inv_slug: str, *, compute_fn=None, force: bool = False,
) -> dict:
    """Topological pull-or-compute over an investigation's member DAG.

    Loads ``investigations/<inv_slug>/investigation.yaml``, reads its member
    list via ``investigation_member_slugs``, and builds a producer DAG from
    each member's ``inputs[].from`` (``study_interface``/``_load_study_spec``
    — the same building blocks ``resolve_study`` uses). A ``from`` producer
    that isn't itself a declared member (e.g. a shared upstream study like
    ``parca``) still becomes a node: ``graphlib.TopologicalSorter.add(node,
    *predecessors)`` implicitly adds any predecessor never explicitly added
    as a dependency-free leaf, so it naturally slots into the order ahead of
    its dependents. Each node in the resulting ``static_order()`` is then
    resolved via ``resolve_study`` in order (NOT recursively re-derived here
    — ``resolve_study`` already recurses into producers on its own; walking
    the topo order here just gives each node an explicit, independently
    reported status).

    Returns:
      {
        "order": [slug, ...],      # topological order (members + producers)
        "nodes": [{"slug", "artifact_id": <id>|None,
                   "status": "cached"|"computed"|"skipped"|"failed",
                   "inputs": [from_slug, ...]}, ...],
        "error": None | str,       # set (only) on a cyclic member DAG
      }

    Status rules:
      - Any upstream (``inputs[].from``) already ``failed``/``skipped`` ->
        this node is ``skipped`` without calling ``resolve_study``.
      - ``resolve_study`` raising for this node -> ``failed`` (caught here,
        never propagates), and its descendants become ``skipped``.
      - A cycle in the member DAG -> ``graphlib.CycleError`` is caught,
        ``error`` is set, and no nodes are resolved (mirrors
        ``resolve_study``'s own ``CyclicDependencyError`` guard, but this
        one is over MEMBERS rather than a single study's producer chain).

    ``force=True`` is passed straight through to every ``resolve_study`` call
    so every node in the DAG bypasses its cache and recomputes (see
    ``resolve_study``'s docstring for why this doesn't need to propagate
    into ``resolve_study``'s own internal producer recursion).
    """
    ws_root = Path(ws_root)
    result: dict = {"order": [], "nodes": [], "error": None}

    try:
        inv_spec = _load_investigation_spec(ws_root, inv_slug)
    except Exception as exc:  # noqa: BLE001 — surfaced via result["error"]
        result["error"] = f"cannot load investigation {inv_slug!r}: {exc}"
        return result

    member_slugs = investigation_member_slugs(inv_spec)

    # Discover every node (members + any producer they transitively pull
    # in, even if that producer isn't itself a declared member) and its own
    # `inputs[].from`, building the sorter as we go.
    inputs_by_slug: dict[str, list[str]] = {}
    ts: graphlib.TopologicalSorter = graphlib.TopologicalSorter()
    seen: set[str] = set()
    queue = list(member_slugs)
    while queue:
        slug = queue.pop()
        if slug in seen:
            continue
        seen.add(slug)
        try:
            spec = _load_study_spec(ws_root, slug)
            froms = [inp["from"] for inp in study_interface(spec)["inputs"]]
        except Exception:  # noqa: BLE001 — unresolvable producer; resolve_study handles it
            froms = []
        inputs_by_slug[slug] = froms
        ts.add(slug, *froms)
        queue.extend(froms)

    try:
        order = list(ts.static_order())
    except graphlib.CycleError as exc:
        result["error"] = f"cyclic member dependency in investigation {inv_slug!r}: {exc}"
        return result

    result["order"] = order

    failed_or_skipped: set[str] = set()
    for slug in order:
        froms = inputs_by_slug.get(slug, [])
        if any(f in failed_or_skipped for f in froms):
            failed_or_skipped.add(slug)
            result["nodes"].append(
                {"slug": slug, "artifact_id": None, "status": "skipped", "inputs": froms}
            )
            continue
        try:
            r = resolve_study(ws_root, slug, compute_fn=compute_fn, force=force)
        except Exception:  # noqa: BLE001 — per-node failure isolation
            failed_or_skipped.add(slug)
            result["nodes"].append(
                {"slug": slug, "artifact_id": None, "status": "failed", "inputs": froms}
            )
            continue
        status = "cached" if r["cached"] else "computed"
        result["nodes"].append(
            {"slug": slug, "artifact_id": r["artifact_id"], "status": status, "inputs": froms}
        )

    return result

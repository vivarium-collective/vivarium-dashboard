"""View for ``POST /api/investigation-resolve`` — the opt-in topological
pull-or-compute endpoint over ``lib.artifacts.pipeline.resolve_investigation``.

This is deliberately separate from ``lib.rerun`` / ``/api/investigation-rerun``
(declared-order rerun, which stays the default and is untouched here): this
endpoint is the content-addressed pull-or-compute path — a cache hit for a
node means it is never recomputed, whereas ``investigation-rerun`` always
force-relaunches every member's baseline.

Increment scope (Task 6): this view runs ``resolve_investigation``
*synchronously* in the request thread — ``resolve_investigation`` ->
``resolve_study`` -> (on a cache miss) ``pipeline._default_compute`` ->
``run_runner.execute`` all execute in-process before the HTTP response is
returned, exactly like ``composite_test_run_views``'s inline path. A fully
detached job variant (mirroring ``run_registry.spawn_detached`` + a CLI
worker subcommand, per the task brief's "preferred" full design) is a
follow-up — out of scope for this opt-in increment, whose goal is a small,
directly testable surface. A large, uncached investigation DAG will block
the request for as long as its studies take to compute; callers that need
non-blocking behavior should keep using the declared-order
``/api/investigation-rerun`` (detached per-study) until that follow-up lands.
"""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib.artifacts.pipeline import resolve_investigation


def resolve_investigation_view(ws_root, investigation: str, *, force: bool = False) -> dict:
    """Run ``resolve_investigation`` for ``investigation`` and shape the result
    for the HTTP response.

    Returns ``{"investigation", "order", "nodes", "error"}`` — ``order``/
    ``nodes``/``error`` are ``resolve_investigation``'s own result verbatim
    (see its docstring for status semantics: cached/computed/skipped/failed,
    and when ``error`` is set instead — e.g. an unknown/cyclic investigation,
    in which case ``order``/``nodes`` are both ``[]``). Always returns (never
    raises) — ``resolve_investigation`` itself already isolates per-node and
    whole-DAG failures into its result, so there is no error path this view
    needs to catch on top of that.
    """
    result = resolve_investigation(Path(ws_root), investigation, force=force)
    return {
        "investigation": investigation,
        "order": result.get("order", []),
        "nodes": result.get("nodes", []),
        "error": result.get("error"),
    }

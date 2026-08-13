"""Canonical ``agents/0/`` scoping fallback.

v2ecoli single-cell composites nest every listener/biology store under
``agents.0....`` (the sole agent's per-cell state), while study readouts,
viz ``inputs_map`` entries, and fingerprint fields are declared at the bare
biology path (e.g. ``listeners/mass/dry_mass``). Every reader that resolves
a declared path against a composite's actual state/history needs the same
two-step lookup: try the literal path first, and if it doesn't resolve,
retry scoped under ``agents/0/``.

This module is the SINGLE source of that fallback in its two forms:
  * :func:`resolve_agents0_fallback` — walk an in-memory state ``dict``
    (used by ``composite_runs`` and ``result_fingerprint``).
  * :func:`agents0_json_extract_pair` — build the matching pair of SQLite
    ``json_extract`` path expressions (used by ``study_charts``,
    ``comparative_viz``, and ``explorer_data``).

Other ``agents/0/`` call sites that were considered and NOT routed through
here because they solve a different problem (see each site's own comment
for why):
  * ``composite_runs.collect_emit_paths_from_spec`` — unconditionally
    expands the emit SET to include both the literal and ``agents/0/``
    form (no state to resolve against yet, so there's no "try, then
    fallback" to share).
  * ``investigations.py`` (``_resolve_series_for_path`` et al.) — resolves
    a *per-tick series* (list-of-values-per-tick) and falls back based on
    whether a usable scalar was found across the series, not on a single
    ``None`` check; a genuinely different resolution rule over a
    genuinely different data shape.
  * ``study_charts._extract_paths_from_parquet`` — resolves a *column
    name* by stripping an ``agents__<id>__`` prefix, the mirror image of
    prepending ``agents.0.`` and against DuckDB/Parquet column names, not
    JSON paths.
  * ``explorer_data._unwrap_agent`` — unconditionally prefers the
    agent-scoped substate (when present) for whole-state-tree browsing;
    it doesn't try a literal path first, so it isn't a "fallback".
"""
from __future__ import annotations

from typing import Any


def resolve_path(state: dict, parts: list[str]) -> Any:
    """Walk ``parts`` (already split path segments) into ``state``.

    Returns the resolved node, or ``None`` if any segment is missing or a
    non-dict is indexed into.
    """
    node = state
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def resolve_agents0_fallback(state: dict,
                              parts: list[str]) -> tuple[list[str], Any]:
    """Resolve ``parts`` against ``state``; retry under ``agents/0/`` if the
    literal path doesn't resolve.

    Returns ``(resolved_parts, node)``: ``resolved_parts`` is ``parts``
    unchanged on a literal hit (or a miss), or ``["agents", "0", *parts]``
    when the agent-scoped form is what actually resolved — callers that
    need to keep using the path (e.g. to walk a subtree) want the form
    that matched, not the one that was declared. ``node`` is ``None`` when
    neither form resolves.
    """
    node = resolve_path(state, parts)
    if node is None and parts[:1] != ["agents"]:
        ag_parts = ["agents", "0"] + parts
        ag_node = resolve_path(state, ag_parts)
        if ag_node is not None:
            return ag_parts, ag_node
    return parts, node


def agents0_json_extract_pair(path: str, idx: int | None) -> tuple[str, str]:
    """Build the ``(literal, agent-scoped)`` pair of SQLite ``json_extract``
    path expressions for one dotted observable ``path`` (+ optional array
    ``idx``).

    e.g. ``agents0_json_extract_pair("listeners.mass.cell_mass", None)`` ->
    ``("$.listeners.mass.cell_mass", "$.agents.0.listeners.mass.cell_mass")``.
    Callers ``json_extract(state, ?)`` (or ``json_each(state, ?)``) each half
    and coalesce, preferring the literal value and falling back to the
    agent-scoped one.
    """
    suffix = f"[{int(idx)}]" if idx is not None and isinstance(idx, int) else ""
    literal = "$." + path + suffix
    agent = "$.agents.0." + path + suffix
    return literal, agent

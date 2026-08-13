"""Workbench-local reason-bearing refusal vocabulary.

P0 of the "typed run→finding chain" design: a small, additive stand-in for
the kernel's ``Crossed | Refusal`` shape (``bigraph_schema.translator.Refusal``,
proposed in bigraph-schema PR #181, unmerged as of this writing). This module
does NOT depend on that PR — it is a workbench-local dataclass with the same
field shape, so a chart/figure that can't be produced can say WHY instead of
silently disappearing or emitting a bare ``needs_manual_refresh``. Once the
kernel's ``Translator``/``Refusal`` ships in bigraph-schema, this module
should be replaced by an import of the real thing rather than grown further.

Used by:
  - ``lib/study_charts.py`` (Boundary G / ``wb.measure.read``) — a behavior
    test's ``measure.path`` with no image in the run's emitted leaves.
  - ``lib/refresh_viz.py`` (Boundary V / ``wb.figure.render``) — a declared
    figure whose optional ``requires: [observable]`` names an observable
    absent from the run's emitted leaves.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Refusal:
    """A reason-bearing refusal: ``{status, reason, missing, present}``.

    ``reason`` is a human-readable sentence naming what's missing and (when
    known) what the store carries instead. ``missing`` / ``present`` are the
    same information in structured form, so a caller can render a chip/badge
    without re-parsing ``reason``.
    """

    reason: str
    missing: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    status: str = "refused"

    def to_dict(self) -> dict:
        return asdict(self)


def _flatten_leaf_paths(node, *, prefix: str = "", max_depth: int = 4, _depth: int = 0):
    """Yield bounded-depth dotted leaf paths under ``node``.

    A "leaf" is any non-dict value (scalar, list, string, ...). Depth is
    bounded so a deeply-nested whole-cell state (e.g. a colony of agents,
    each a full sub-model) can't make a refusal message itself expensive to
    build — this backs a human-readable ``present`` list, not an exhaustive
    manifest (that's the design's later ``wb.run.to_dialect`` leaf-manifest
    work, recorded at write time; this is a best-effort read-time stand-in).
    """
    if isinstance(node, dict) and _depth < max_depth:
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                yield from _flatten_leaf_paths(
                    v, prefix=path, max_depth=max_depth, _depth=_depth + 1)
            else:
                yield path
    elif prefix:
        yield prefix


def present_leaves_from_runs_db(runs_db: "Path | None", *, max_leaves: int = 40) -> list[str]:
    """Best-effort leaf-path manifest of a study's latest run.

    Reads ``runs_db`` (the ``simulations``/``history`` sqlite tables, one
    full-state JSON blob per row) and flattens the latest row's state to
    bounded-depth dotted leaf paths. This is the sqlite-dialect case; a
    zarr/parquet-backed run's leaves are not enumerated here (see callers for
    a narrower fallback in that case). Never raises — a refusal's ``present``
    field is advisory, not something that should itself crash the refusal.
    """
    if runs_db is None:
        return []
    runs_db = Path(runs_db)
    if not runs_db.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{runs_db}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return []
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "simulations" not in tables or "history" not in tables:
            return []
        row = conn.execute(
            "SELECT simulation_id FROM simulations ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return []
        sim_id = row[0]
        state_row = conn.execute(
            "SELECT state FROM history WHERE simulation_id=? ORDER BY step DESC LIMIT 1",
            (sim_id,),
        ).fetchone()
        if state_row is None or state_row[0] is None:
            return []
        import json
        state = json.loads(state_row[0])
    except (sqlite3.Error, ValueError, TypeError):
        return []
    finally:
        conn.close()
    leaves = sorted(set(_flatten_leaf_paths(state)))
    return leaves[:max_leaves]

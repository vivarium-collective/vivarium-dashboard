"""Shared post-hoc observable extraction from a runs.db.

This is the single place that knows how to pull observable time-series out
of a simulation history database. Before this module existed the same
logic was copy-pasted three times — in ``study_charts._extract_paths_from_db``,
``comparative_viz._extract_trace``, and (in a dict-walking variant)
``investigations._resolve_observable`` — and each copy independently grew
(or missed) the same handling for:

  - SQLite ``json_extract`` (read only the requested scalar paths, never
    transfer multi-MB state blobs to Python),
  - the per-agent scope fallback (v2ecoli single-cell composites scope
    listener stores under ``agents.0.*`` even though study/investigation
    yamls declare the biology path, e.g. ``listeners.dnaA_cycle.atp_fraction``),
  - empty-container literals (a declared path that resolves to ``{}`` —
    created when emit_paths declares both the literal and agent-scoped
    forms — must fall through to the agent-scoped value),
  - subsampling to a target point budget,
  - sim selection (latest started, or by name with a runs_meta fallback).

Step 1 of the viz-decoupling refactor (see friction-log #19): all
SQL-based viz pipelines route through ``extract_series`` so the resolution
logic lives once. Multi-run gather + render-kind decoupling are later steps.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

# Dotted alphanumeric + underscore only. Bracket-style bulk-id paths
# (``bulk[MONOMER0-160]``) aren't expressible in json_extract path syntax,
# so callers' specs with such paths are skipped rather than raising.
_PATH_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")

PathSpec = tuple[str, "int | None"]
Series = tuple[list[float], list[float]]  # (times, values)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def resolve_sim_id(conn: sqlite3.Connection,
                   sim_name: str | None = None) -> str | None:
    """Pick a ``simulation_id`` from the db.

    With ``sim_name``: prefer ``simulations.name`` (set by some emit
    pipelines), fall back to ``runs_meta.sim_name`` (what the dashboard's
    run-variant path populates; ``simulation_id`` in history == ``run_id``
    in runs_meta). Without: the most-recently-started simulation.
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "simulations" not in tables or "history" not in tables:
        return None
    if sim_name:
        row = conn.execute(
            "SELECT simulation_id FROM simulations WHERE name=? "
            "ORDER BY started_at DESC LIMIT 1", (sim_name,)
        ).fetchone()
        if row is None and "runs_meta" in tables:
            row = conn.execute(
                "SELECT run_id FROM runs_meta WHERE sim_name=? "
                "ORDER BY started_at DESC LIMIT 1", (sim_name,)
            ).fetchone()
    else:
        row = conn.execute(
            "SELECT simulation_id FROM simulations ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else None


def _num(v) -> float | None:
    """Coerce to float, or None for null / container / non-numeric. An empty
    ``{}`` (a path resolving to a store with no scalar) is not numeric, so it
    falls through to the agent-scoped candidate."""
    if v is None or isinstance(v, (dict, list)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract_series(
    db_path: Path | str,
    path_specs: list[PathSpec],
    *,
    max_points: int = 200,
    sim_name: str | None = None,
) -> dict[PathSpec, Series]:
    """Extract ``{(path, index): (times, values)}`` for one simulation.

    One ``json_extract(state, '$.lit', '$.agents.0.lit')`` per path: SQLite's
    multi-path form returns a 2-element JSON array from a SINGLE parse of the
    state blob, so the per-agent fallback costs nothing extra (critical for
    multi-MB state rows). Prefer the numeric literal value; fall through to
    the numeric agent-scoped value.

    Returns a dict keyed by the original specs; specs whose path isn't
    json_extract-expressible, or that resolve to nothing, map to ``([], [])``.
    """
    out: dict[PathSpec, Series] = {key: ([], []) for key in path_specs}
    if not path_specs:
        return out
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.OperationalError:
        return out
    try:
        sim_id = resolve_sim_id(conn, sim_name=sim_name)
        if sim_id is None:
            return out
        n_rows = conn.execute(
            "SELECT COUNT(*) FROM history WHERE simulation_id=?", (sim_id,)
        ).fetchone()[0] or 0
        if n_rows == 0:
            return out
        stride = max(1, n_rows // max_points)

        supported = [(p, i) for (p, i) in path_specs if _PATH_RE.match(p)]
        if not supported:
            return out

        select_cols = ["global_time"]
        params: list = []
        for path, idx in supported:
            suffix = (f"[{int(idx)}]"
                      if idx is not None and isinstance(idx, int) else "")
            select_cols.append("json_extract(state, ?, ?)")
            params.append("$." + path + suffix)
            params.append("$.agents.0." + path + suffix)
        sql = (
            f"SELECT {', '.join(select_cols)} FROM history "
            f"WHERE simulation_id=? AND (step % ?) = 0 ORDER BY step ASC"
        )
        params += [sim_id, stride]

        for row in conn.execute(sql, params):
            tm = _num(row[0])
            if tm is None:
                # global_time column is NULL for some emit pipelines
                # (e.g. v2ecoli baselines where global_time isn't wired
                # into the captured state). Without an x-coordinate the
                # point can't be plotted; skip the row rather than crash.
                continue
            for i, key in enumerate(supported):
                cell = row[1 + i]
                if cell is None:
                    continue
                try:
                    pair = json.loads(cell)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                v_lit = _num(pair[0]) if len(pair) > 0 else None
                v_agent = _num(pair[1]) if len(pair) > 1 else None
                v = v_lit if v_lit is not None else v_agent
                if v is None:
                    continue
                out[key][1].append(v)
                out[key][0].append(tm)
        return out
    finally:
        conn.close()


def extract_trace(
    db_path: Path | str,
    observable_path: str,
    observable_index: int | None = None,
    *,
    max_points: int = 200,
    sim_name: str | None = None,
) -> Series:
    """Single-observable convenience wrapper over :func:`extract_series`."""
    key: PathSpec = (observable_path, observable_index)
    return extract_series(
        db_path, [key], max_points=max_points, sim_name=sim_name,
    ).get(key, ([], []))

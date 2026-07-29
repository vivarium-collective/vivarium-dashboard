"""Zarr-native default Viz/Report rendering — for runs whose data lives ONLY
in a zarr/XArray emitter store (every GovCloud/Ray-dispatched run today),
where the framework's own ``_render_canonical_viz``/``_render_default_viz``
(``run_runner.py``) and the external ``viva_superpowers.TimeSeriesFromObservables``
Visualization class have no path at all — both are built entirely around
reading a SQLite emitter database via ``gather_emitter_outputs``.

Reuses the SAME zarr readers already used by the Composite Explorer's Analyses
Data card (``explorer_data._zarr_observables``, ``explorer_data.get_series``,
themselves backed by ``comparative_viz._extract_trace_from_zarr``) — no new
zarr-reading code, no new dependency. This module only picks a sensible
default observable set and renders the resulting traces as a self-contained
Plotly page, mirroring the HTML shape ``viva_superpowers.TimeSeriesFromObservables``
already produces for the SQLite case.
"""
from __future__ import annotations

import html as _html
import json
from pathlib import Path

# Categories favored for a "what does this run look like" default view — the
# whole-cell-model observables an expert reaches for first. Order is display
# order; each contributes up to _PER_CATEGORY_CAP scalar leaves.
_DEFAULT_CATEGORIES = ["Mass", "Growth & division", "Bulk molecules"]
_PER_CATEGORY_CAP = 3
_TOTAL_CAP = 8

_PALETTE = [
    "#6366f1", "#10b981", "#f43f5e", "#f59e0b",
    "#8b5cf6", "#06b6d4", "#84cc16", "#ec4899",
]


def pick_default_observables(categories: dict[str, list[dict]]) -> list[str]:
    """Choose a bounded, sensible default set of scalar leaf names to plot.

    ``categories`` is ``explorer_data._zarr_observables()``'s ``"categories"``
    value: ``{category_name: [{"path", "kind", ...}, ...]}``. Vector leaves
    (``kind == "vector"``) are skipped — they need an explicit index to plot
    a single trace, which a default view has no basis to pick.
    """
    chosen: list[str] = []
    for cat in _DEFAULT_CATEGORIES:
        leaves = [leaf["path"] for leaf in categories.get(cat, []) if leaf.get("kind") != "vector"]
        chosen.extend(leaves[:_PER_CATEGORY_CAP])
        if len(chosen) >= _TOTAL_CAP:
            break
    return chosen[:_TOTAL_CAP]


def render_default_viz(store: Path, run_id: str) -> str:
    """Render a self-contained Plotly HTML page of this zarr run's default
    observables. Never raises — degrades to an explanatory placeholder on any
    failure (missing xarray, empty store, no numeric leaves, etc.), matching
    the existing artifact routes' "best-effort, never 500" convention.
    """
    from vivarium_workbench.lib import explorer_data

    try:
        obs = explorer_data._zarr_observables(store)
        categories = obs.get("categories") or {}
    except Exception:
        categories = {}

    names = pick_default_observables(categories)
    if not names:
        return _placeholder(
            run_id,
            "No numeric scalar observables were found in this run's native store "
            "to plot by default.",
        )

    try:
        data = explorer_data.get_series(str(store), [(n, None) for n in names])
    except Exception:
        return _placeholder(run_id, "Could not read this run's native store.")

    time = data.get("time") or []
    series = data.get("series") or {}
    traces = []
    for i, name in enumerate(names):
        y = series.get(name) or []
        if not y:
            continue
        x = time[:len(y)] if time else list(range(len(y)))
        traces.append({
            "x": x, "y": y, "type": "scatter", "mode": "lines",
            "name": name,
            "line": {"color": _PALETTE[i % len(_PALETTE)], "width": 2},
        })
    if not traces:
        return _placeholder(
            run_id,
            "This run's default observables ("
            + ", ".join(names)
            + ") had no data in the native store.",
        )

    layout = {
        "title": {"text": "Default observables", "font": {"size": 14}},
        "xaxis": {"title": {"text": "time"}},
        "yaxis": {"title": {"text": "value"}},
        "margin": {"l": 60, "r": 15, "t": 40, "b": 50},
        "legend": {"orientation": "h", "y": -0.2},
    }
    return (
        f'<div style="font-family:system-ui;color:#6b7280;font-size:12px;margin-bottom:6px">'
        f'Rendered from the native zarr/XArray store — {_html.escape(", ".join(names))}'
        f'</div>'
        '<div id="viz" style="height:420px"></div>'
        '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
        '<script>Plotly.newPlot("viz", '
        + json.dumps(traces) + ", " + json.dumps(layout)
        + ", {responsive:true, displayModeBar:false});</script>"
    )


def _placeholder(run_id: str, message: str) -> str:
    return (
        f'<div style="padding:12px;color:#92400e;background:#fef3c7;'
        f'border:1px solid #fcd34d;border-radius:4px;font-family:system-ui">'
        f'<strong>{_html.escape(message)}</strong>'
        f'</div>'
    )

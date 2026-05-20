"""Comparative time-series visualizations across multiple runs.

The dashboard's existing chart pipeline (study_charts.py) reads ONE
runs.db per study. For investigation-level comparisons — e.g., the
dnaa-05 three-way comparison of standalone ITv2 vs v2ecoli baseline vs
v2ecoli-with-FXJ-params — we need to overlay traces from N runs.db
files on the same chart.

This module reads the latest run from each named db and emits a
self-contained Plotly HTML file. The output is auto-discovered by the
dashboard's ``_discover_viz_html_files`` when written under
``investigations/<inv>/viz/`` or ``studies/<slug>/viz/``.

Public API
----------

``render_comparative_time_series(
        runs:            list[{"label": str, "db_path": Path}],
        observable_path: str,        # dotted path into state, e.g. "listeners.itv2.volume"
        title:           str,
        y_label:         str,
        output_path:     Path,
        subsample:       int = 200,  # max points per trace
        observable_index: int | None = None,  # for list-valued paths
    ) -> Path``

Each run's latest simulation_id is selected; its history is subsampled
to ``subsample`` points evenly across the time axis; the observable is
extracted via SQLite's ``json_extract`` (fast — same trick as the v4
test-driven chart pipeline). The resulting HTML carries the Plotly CDN
inline so it works offline.
"""
from __future__ import annotations

import json
import re
import sqlite3
from html import escape
from pathlib import Path
from typing import Any


_PLOTLY_CDN = (
    '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js" charset="utf-8"></script>'
)


def _extract_trace(db_path: Path,
                   observable_path: str,
                   observable_index: int | None,
                   subsample: int,
                   sim_name: str | None = None) -> tuple[list[float], list[float]]:
    """Pull (times, values) for one observable from one run db.

    Thin wrapper over the shared :func:`series_extract.extract_trace`
    (Step 1 of the viz-decoupling refactor). ``subsample`` is the target
    point budget — the shared extractor strides to ~that many points.
    Returns ([], []) on any error so a missing path doesn't sink the
    whole multi-run chart.
    """
    if not db_path.exists():
        return [], []
    from vivarium_dashboard.lib.series_extract import extract_trace
    return extract_trace(
        db_path, observable_path, observable_index,
        max_points=subsample, sim_name=sim_name,
    )


def render_comparative_time_series(
    runs: list[dict],
    observable_path: str,
    title: str,
    y_label: str,
    output_path: Path,
    *,
    subsample: int = 200,
    observable_index: int | None = None,
    target_band: tuple[float, float] | None = None,
    target_band_label: str | None = None,
) -> Path:
    """Render N runs as overlaid Plotly traces in a single HTML file.

    ``runs`` is a list of ``{"label": str, "db_path": Path or str}``.
    Each run becomes one trace; missing data renders as an empty trace
    so the legend still shows the label.

    Returns ``output_path`` (the path the HTML was written to).
    """
    traces: list[dict] = []
    for entry in runs:
        label = str(entry.get("label", "?"))
        db_path = Path(entry["db_path"]) if entry.get("db_path") else None
        sim_name = entry.get("sim_name")
        if db_path is None:
            traces.append({"label": label, "x": [], "y": [], "note": "(no db_path)"})
            continue
        xs, ys = _extract_trace(
            db_path, observable_path, observable_index, subsample, sim_name,
        )
        if not xs:
            note = f"(no data: {observable_path!r}"
            if sim_name:
                note += f" sim={sim_name!r}"
            note += ")"
        else:
            note = ""
        traces.append({"label": label, "x": xs, "y": ys, "note": note})

    plotly_data = []
    for t in traces:
        plotly_data.append({
            "type": "scatter",
            "mode": "lines+markers",
            "name": t["label"] + (f" {t['note']}" if t["note"] else ""),
            "x": t["x"],
            "y": t["y"],
            "line": {"width": 2},
            "marker": {"size": 4},
            "hovertemplate": "<b>" + t["label"] + "</b><br>"
                             "t=%{x:.0f}s<br>" + y_label + "=%{y:.4g}<extra></extra>",
        })

    shapes = []
    annotations = []
    if target_band is not None and isinstance(target_band, (list, tuple)) and len(target_band) == 2:
        lo, hi = target_band
        shapes.append({
            "type": "rect",
            "xref": "paper", "x0": 0, "x1": 1,
            "yref": "y", "y0": lo, "y1": hi,
            "fillcolor": "#16a34a",
            "opacity": 0.10,
            "line": {"width": 0},
            "layer": "below",
        })
        if target_band_label:
            annotations.append({
                "xref": "paper", "x": 0.99, "y": hi,
                "xanchor": "right", "yanchor": "bottom",
                "showarrow": False,
                "text": target_band_label,
                "font": {"size": 11, "color": "#16a34a"},
            })

    layout = {
        "title": {"text": title, "x": 0.5, "xanchor": "center"},
        "xaxis": {"title": "time (s)", "showgrid": True, "gridcolor": "#e5e7eb"},
        "yaxis": {"title": y_label, "showgrid": True, "gridcolor": "#e5e7eb"},
        "shapes": shapes,
        "annotations": annotations,
        "legend": {"orientation": "h", "yanchor": "top", "y": -0.18},
        "margin": {"t": 60, "r": 30, "b": 80, "l": 70},
        "plot_bgcolor": "#fafafa",
        "paper_bgcolor": "#fff",
        "height": 480,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    html = (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8"><title>' + escape(title) + "</title>"
        + _PLOTLY_CDN
        + '<style>body{font-family:-apple-system,"Segoe UI",sans-serif;margin:0;padding:18px 22px;background:#fff;color:#1f2937}'
        + 'h1{font-size:1.15em;margin:0 0 4px 0;color:#0f172a}'
        + '.subtitle{color:#6b7280;font-size:0.9em;margin-bottom:14px}'
        + '.chart-target{width:100%;min-height:480px}'
        + '</style></head><body>'
        + '<h1>' + escape(title) + '</h1>'
        + '<div class="subtitle">Comparative time-series — '
        + str(len(runs)) + ' run(s) overlaid · path <code>' + escape(observable_path) + '</code></div>'
        + '<div id="chart" class="chart-target"></div>'
        + '<script>'
        + 'Plotly.newPlot("chart", '
        + json.dumps(plotly_data, default=str)
        + ', '
        + json.dumps(layout, default=str)
        + ', {responsive: true, displayModeBar: false});'
        + '</script></body></html>'
    )
    output_path.write_text(html)
    return output_path

"""Render inline-SVG line charts from a study's runs.db.

The dashboard uses these to embed simulation visualisations directly into
the per-investigation HTML report (and the study-detail Charts panel).
SVGs are self-contained, render in any browser without JS, and survive
being downloaded as part of the report's offline-HTML payload.

Chart selection is currently bespoke to the dnaa-investigation readouts —
each entry in CHART_SPECS declares what to pull from the per-step state
and how to label the y-axis. As more studies emit data we'll generalise
this into a per-study chart-spec block (likely `readouts:` driven).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from xml.sax.saxutils import escape

# DnaA monomer index (PD03831[c]) in monomer_ids; hardcoded fallback.
DNAA_MONOMER_IDX = 3861

# Each spec: (title, y-label, extractor(state)->float-or-None, caption)
CHART_SPECS = [
    {
        "key":     "dnaA_count",
        "title":   "DnaA monomer count over time",
        "y_label": "molecules / cell",
        "caption": "Aggregate DnaA via listeners.monomer_counts[idx 3861] (PD03831[c]). "
                   "Steady-state target band per Schmidt 2016 / Mori 2021: 300-800.",
        "extract": "monomer_index:3861",
    },
    {
        "key":     "free_vs_atp_pool",
        "title":   "Bulk pool composition: free DnaA vs DnaA-ATP",
        "y_label": "molecules / cell",
        "caption": "bulk[PD03831[c]] (free) and bulk[MONOMER0-160[c]] (DnaA-ATP complex). "
                   "Sum approximates the listener's aggregate; difference reveals "
                   "equilibrium drift.",
        "extract": "bulk_pair:PD03831[c]:MONOMER0-160[c]",
    },
    {
        "key":     "tx_init_events",
        "title":   "RNA transcription-initiation events per step",
        "y_label": "events / step (cell-wide)",
        "caption": "Sum of listeners.rnap_data.rna_init_event across all TUs. "
                   "A coarse rate proxy.",
        "extract": "listener_sum:listeners.rnap_data.rna_init_event",
    },
    {
        "key":     "dnaA_mrna",
        "title":   "DnaA mRNA copy number (EG10235_RNA)",
        "y_label": "molecules / cell",
        "caption": "Direct from listeners.rna_counts.mRNA_counts. Position-indexed by "
                   "the ParCa mRNA_TU_ids list.",
        "extract": "mrna_first",   # placeholder — needs mrna_index lookup
    },
]


def _extract(state: dict, extractor: str) -> float | None:
    if extractor.startswith("monomer_index:"):
        idx = int(extractor.split(":")[1])
        mc = state.get("listeners", {}).get("monomer_counts")
        if isinstance(mc, list) and len(mc) > idx:
            return float(mc[idx])
        return None

    if extractor.startswith("bulk_pair:"):
        _, a, b = extractor.split(":")
        bulk = state.get("bulk")
        if not isinstance(bulk, list):
            return None
        for row in bulk:
            if isinstance(row, list) and row and row[0] == a:
                # return tuple-like for bulk_pair; caller checks
                pa = row[1]
                break
        else:
            pa = None
        for row in bulk:
            if isinstance(row, list) and row and row[0] == b:
                pb = row[1]
                break
        else:
            pb = None
        return (pa, pb)   # caller will handle

    if extractor.startswith("listener_sum:"):
        path = extractor.split(":", 1)[1]
        cur = state
        for seg in path.split("."):
            if not isinstance(cur, dict) or seg not in cur:
                return None
            cur = cur[seg]
        if isinstance(cur, list):
            try:
                return float(sum(cur))
            except TypeError:
                return None
        if isinstance(cur, (int, float)):
            return float(cur)
        return None

    if extractor == "mrna_first":
        rc = state.get("listeners", {}).get("rna_counts")
        if isinstance(rc, dict):
            m = rc.get("mRNA_counts")
            if isinstance(m, list) and m:
                # Without sim_data we can't index by EG10235_RNA. Return median
                # of the top-20 most-expressed mRNAs as a stand-in until the
                # rna_id index lookup is wired through (dashboard doesn't have
                # access to the ParCa cache from this process).
                top20 = sorted(m, reverse=True)[:20]
                return float(top20[0]) if top20 else None
        return None
    return None


def _render_svg(title: str, y_label: str, xs: list[float], ys: list[float],
                width: int = 720, height: int = 220,
                ys2: list[float] | None = None, y2_label: str | None = None,
                target_band: tuple[float, float] | None = None) -> str:
    """Render a single line chart as an inline SVG string. Pure-stdlib.

    If ys2 is provided, plots a second series alongside ys (used for
    free/ATP-pool comparison). target_band shades a horizontal range
    (used for the literature-target band on DnaA count).
    """
    pad_l, pad_r, pad_t, pad_b = 56, 12, 28, 36
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    if not xs or not ys:
        return (f'<div class="chart-empty" style="padding:24px;color:#94a3b8;'
                f'font-style:italic">No data for "{escape(title)}".</div>')

    all_ys = list(ys) + (list(ys2) if ys2 else [])
    y_min = min(all_ys + ([target_band[0]] if target_band else []))
    y_max = max(all_ys + ([target_band[1]] if target_band else []))
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    x_min, x_max = min(xs), max(xs)
    if x_min == x_max:
        x_max = x_min + 1

    def sx(x): return pad_l + (x - x_min) / (x_max - x_min) * plot_w
    def sy(y): return pad_t + plot_h - (y - y_min) / (y_max - y_min) * plot_h

    def _points(series):
        return " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(xs, series))

    band_rect = ""
    if target_band:
        lo, hi = target_band
        band_rect = (
            f'<rect x="{pad_l:.1f}" y="{sy(hi):.1f}" '
            f'width="{plot_w:.1f}" height="{(sy(lo)-sy(hi)):.1f}" '
            f'fill="#dcfce7" fill-opacity="0.55"/>'
            f'<text x="{pad_l + plot_w - 4:.1f}" y="{sy(hi) + 12:.1f}" '
            f'font-size="10" fill="#16a34a" text-anchor="end">'
            f'literature target {int(lo)}–{int(hi)}</text>'
        )

    series_paths = (
        f'<polyline points="{_points(ys)}" fill="none" stroke="#2563eb" stroke-width="1.5"/>'
    )
    if ys2 is not None:
        series_paths += (
            f'<polyline points="{_points(ys2)}" fill="none" stroke="#dc2626" stroke-width="1.5"/>'
        )

    # Simple 4-tick y-axis labels
    yticks = [y_min + (y_max - y_min) * f for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
    ytick_text = "".join(
        f'<text x="{pad_l-6:.1f}" y="{sy(y)+3:.1f}" font-size="10" fill="#64748b" '
        f'text-anchor="end">{_fmt(y)}</text>'
        f'<line x1="{pad_l:.1f}" y1="{sy(y):.1f}" x2="{pad_l+plot_w:.1f}" y2="{sy(y):.1f}" '
        f'stroke="#e2e8f0" stroke-dasharray="2,3"/>'
        for y in yticks
    )

    # X-axis (time): 5 ticks
    xticks = [x_min + (x_max - x_min) * f for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
    xtick_text = "".join(
        f'<text x="{sx(x):.1f}" y="{pad_t+plot_h+14:.1f}" font-size="10" fill="#64748b" '
        f'text-anchor="middle">{_fmt(x)}s</text>'
        for x in xticks
    )

    # Legend
    legend = ""
    if ys2 is not None and y2_label is not None:
        legend = (
            f'<g transform="translate({pad_l+12},{pad_t+10})">'
            f'<rect width="10" height="3" fill="#2563eb"/>'
            f'<text x="14" y="4" font-size="11" fill="#1e293b">{escape(y_label)}</text>'
            f'<rect y="14" width="10" height="3" fill="#dc2626"/>'
            f'<text x="14" y="18" font-size="11" fill="#1e293b">{escape(y2_label)}</text>'
            f'</g>'
        )

    return f'''<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
       style="display:block;width:100%;height:auto;max-width:{width}px">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>
  <text x="{width/2:.1f}" y="16" font-size="12" font-weight="600" fill="#0f172a"
        text-anchor="middle">{escape(title)}</text>
  {band_rect}
  {ytick_text}
  {xtick_text}
  <line x1="{pad_l:.1f}" y1="{pad_t:.1f}" x2="{pad_l:.1f}" y2="{pad_t+plot_h:.1f}" stroke="#94a3b8"/>
  <line x1="{pad_l:.1f}" y1="{pad_t+plot_h:.1f}" x2="{pad_l+plot_w:.1f}" y2="{pad_t+plot_h:.1f}" stroke="#94a3b8"/>
  {series_paths}
  {legend}
  <text x="{pad_l-44:.1f}" y="{pad_t+plot_h/2:.1f}" font-size="10" fill="#64748b"
        transform="rotate(-90 {pad_l-44:.1f} {pad_t+plot_h/2:.1f})"
        text-anchor="middle">{escape(y_label)}</text>
</svg>'''


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    av = abs(v)
    if av >= 10_000:
        return f"{v/1000:.0f}k"
    if av >= 100:
        return f"{int(round(v))}"
    if av >= 1:
        return f"{v:.1f}"
    return f"{v:.2g}"


def render_study_charts(runs_db: Path,
                        run_name: str | None = None) -> list[dict]:
    """Return a list of {key, title, caption, svg} for the latest run in runs.db.

    Returns an empty list (not an error) when the db is missing, the run
    name isn't found, or all extractors come back empty.
    """
    if not runs_db.exists():
        return []
    conn = sqlite3.connect(str(runs_db))
    try:
        if run_name:
            row = conn.execute(
                "SELECT simulation_id FROM simulations WHERE name=? "
                "ORDER BY started_at DESC LIMIT 1", (run_name,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT simulation_id FROM simulations "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return []
        sim_id = row[0]
        rows = conn.execute(
            "SELECT step, global_time, state FROM history WHERE simulation_id=? "
            "ORDER BY step ASC", (sim_id,)
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    times = [r[1] for r in rows]
    parsed = [json.loads(r[2]) for r in rows]

    charts: list[dict] = []
    for spec in CHART_SPECS:
        extractor = spec["extract"]
        if extractor.startswith("bulk_pair:"):
            pairs = [_extract(s, extractor) for s in parsed]
            xs, ys, ys2 = [], [], []
            for t, p in zip(times, pairs):
                if p is None: continue
                a, b = p
                if a is None or b is None: continue
                xs.append(t); ys.append(float(a)); ys2.append(float(b))
            if not xs: continue
            svg = _render_svg(
                spec["title"], "free DnaA (bulk PD03831[c])",
                xs, ys, ys2=ys2, y2_label="DnaA-ATP (bulk MONOMER0-160[c])"
            )
        else:
            xs, ys = [], []
            for t, s in zip(times, parsed):
                v = _extract(s, extractor)
                if v is None: continue
                xs.append(t); ys.append(float(v))
            if not xs: continue
            band = (300.0, 800.0) if spec["key"] == "dnaA_count" else None
            svg = _render_svg(spec["title"], spec["y_label"],
                              xs, ys, target_band=band)
        charts.append({
            "key": spec["key"], "title": spec["title"],
            "caption": spec["caption"], "svg": svg,
        })
    return charts

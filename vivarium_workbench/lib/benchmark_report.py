"""Render a study-automation benchmark_report/v1 as a static HTML page.

Pure/AI-free (workbench owns rendering; the plugin owns judgment). Consumes the
`benchmark_report/v1` dict the `/viva-benchmark` skill writes — the per-trial
rubric axes + the aggregate + the framework variant — into a results **heatmap**
(items × rubric axes) plus an aggregate summary, and renders a **variant-diff**
between two runs (which axes improved / regressed when the library changed). See
the benchmark spec §7.
"""
from __future__ import annotations

import html as _html

# Verdict → cell color + score (matches the /v2 palette).
_COLOR = {"within_tol": "#16a34a", "drift": "#d97706",
          "mismatch": "#dc2626", "ungraded": "#6b7280"}
_SCORE = {"within_tol": 1.0, "drift": 0.5, "mismatch": 0.0, "ungraded": None}
# The rubric axis order (stable columns).
_AXES = ("test_sufficiency", "loop_outcome", "model_plausibility",
         "question_comprehension", "efficiency")


def _e(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _axes_of(trial_report: dict) -> dict:
    return {a.get("id"): a for g in (trial_report.get("groups") or {}).values()
            for a in (g.get("axes") or [])}


def _cell(verdict: str) -> str:
    c = _COLOR.get(verdict, _COLOR["ungraded"])
    return (f'<td style="background:{c};color:#fff;text-align:center;padding:5px 8px;'
            f'font-size:0.78em" title="{_e(verdict)}">{_e((verdict or "–")[:1].upper())}</td>')


def _pct(x) -> str:
    return f"{x*100:.0f}%" if isinstance(x, (int, float)) else "—"


def render_benchmark_report(report: dict) -> str:
    """A results page: the aggregate summary + an items×axes rubric heatmap."""
    report = report if isinstance(report, dict) else {}
    agg = report.get("aggregate") or {}
    variant = report.get("variant") or {}
    trials = report.get("trials") or []

    vbits = " · ".join(f"{_e(k)}: <code>{_e(v)}</code>" for k, v in variant.items() if v)
    gamed = agg.get("gamed_pass_rate")
    gamed_html = (f'<span style="color:{"#dc2626" if (gamed or 0) > 0 else "#16a34a"};'
                  f'font-weight:600">gamed-pass {_pct(gamed)}</span>')
    summary = (
        '<div style="display:flex;gap:16px;flex-wrap:wrap;margin:4px 0 14px;font-size:0.92em">'
        f'<span><strong>{int(agg.get("n") or 0)}</strong> trials</span>'
        f'<span>mean {_pct(agg.get("mean_overall"))}</span>'
        f'<span>pass-rate {_pct(agg.get("pass_rate"))}</span>'
        f'<span>honest-giveup {_pct(agg.get("honest_giveup_rate"))}</span>'
        f'{gamed_html}</div>')

    head = ('<tr><th style="text-align:left;padding:5px 8px">Item</th>'
            '<th style="padding:5px 8px">Overall</th>'
            + "".join(f'<th style="padding:5px 8px;font-size:0.7em;writing-mode:vertical-rl;'
                      f'transform:rotate(180deg)">{_e(a.replace("_", " "))}</th>' for a in _AXES)
            + "</tr>")
    rows = []
    for t in trials:
        axes = _axes_of(t.get("report") or {})
        overall = (t.get("report") or {}).get("overall", "ungraded")
        cells = "".join(_cell(axes.get(a, {}).get("verdict", "ungraded")) for a in _AXES)
        rows.append(f'<tr style="border-top:1px solid #eef2f7">'
                    f'<td style="padding:5px 8px;font-family:monospace;font-size:0.85em">{_e(t.get("item"))}</td>'
                    f'{_cell(overall)}{cells}</tr>')

    return (
        '<section id="benchmark"><h2>Benchmark — '
        f'{_e(report.get("suite"))}</h2>'
        f'<div style="color:#475569;font-size:0.88em;margin:0 0 4px">{vbits or "no variant recorded"}</div>'
        + summary +
        '<table style="border-collapse:collapse;font-size:0.9em">'
        f'<thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'
        '<p style="color:#64748b;font-size:0.8em;margin-top:6px">'
        'Cells: ✓ within_tol · ≈ drift · ✗ mismatch · – ungraded. '
        'A non-zero gamed-pass rate means the loop is passing tests it should not — investigate.'
        '</p></section>')


def render_variant_diff(report_a: dict, report_b: dict) -> str:
    """Compare two runs of the SAME suite: per-axis mean Δ (B − A) and which items
    flipped their overall verdict. The eval-driven-development signal."""
    a, b = report_a or {}, report_b or {}
    agg_a, agg_b = (a.get("aggregate") or {}), (b.get("aggregate") or {})
    la = (a.get("variant") or {}).get("skills_label") or "A"
    lb = (b.get("variant") or {}).get("skills_label") or "B"

    def _by_axis(agg):
        return agg.get("by_axis") or {}
    rows = []
    for metric in ("mean_overall", "pass_rate", "honest_giveup_rate", "gamed_pass_rate"):
        va, vb = agg_a.get(metric), agg_b.get(metric)
        d = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        color = "#6b7280"
        if isinstance(d, (int, float)) and d != 0:
            better = d > 0 if metric != "gamed_pass_rate" else d < 0
            color = "#16a34a" if better else "#dc2626"
        rows.append(f'<tr><td style="padding:4px 8px">{_e(metric)}</td>'
                    f'<td style="padding:4px 8px;text-align:right">{_pct(va)}</td>'
                    f'<td style="padding:4px 8px;text-align:right">{_pct(vb)}</td>'
                    f'<td style="padding:4px 8px;text-align:right;color:{color};font-weight:600">'
                    f'{("+" if isinstance(d,(int,float)) and d>0 else "")}{_pct(d) if d is not None else "—"}</td></tr>')
    for aid in _AXES:
        va, vb = _by_axis(agg_a).get(aid), _by_axis(agg_b).get(aid)
        d = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        color = "#6b7280" if not d else ("#16a34a" if d > 0 else "#dc2626")
        rows.append(f'<tr><td style="padding:4px 8px;color:#475569">axis: {_e(aid)}</td>'
                    f'<td style="padding:4px 8px;text-align:right">{_pct(va)}</td>'
                    f'<td style="padding:4px 8px;text-align:right">{_pct(vb)}</td>'
                    f'<td style="padding:4px 8px;text-align:right;color:{color};font-weight:600">'
                    f'{("+" if isinstance(d,(int,float)) and d>0 else "")}{_pct(d) if d is not None else "—"}</td></tr>')

    return (
        f'<section id="benchmark-diff"><h2>Variant diff — {_e(la)} → {_e(lb)}</h2>'
        '<table style="border-collapse:collapse;font-size:0.9em">'
        f'<thead><tr><th style="text-align:left;padding:4px 8px">metric</th>'
        f'<th style="padding:4px 8px">{_e(la)}</th><th style="padding:4px 8px">{_e(lb)}</th>'
        '<th style="padding:4px 8px">Δ</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        '<p style="color:#64748b;font-size:0.8em;margin-top:6px">Green = the change improved that '
        'metric (for gamed-pass, lower is better). Compare only runs of the same suite.</p></section>')

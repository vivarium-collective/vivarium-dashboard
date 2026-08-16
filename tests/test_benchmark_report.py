"""benchmark_report render: a benchmark_report/v1 → results heatmap + variant-diff."""
from vivarium_workbench.lib.benchmark_report import (
    render_benchmark_report, render_variant_diff)


def _trial(item_id, overall, axes):
    return {"item": item_id,
            "report": {"overall": overall,
                       "groups": {"rubric": {"axes": [
                           {"id": k, "verdict": v} for k, v in axes.items()]}}}}


def _report(suite, variant, agg, trials):
    return {"schema": "benchmark_report/v1", "suite": suite, "variant": variant,
            "aggregate": agg, "trials": trials}


_RUN_A = _report(
    "suite-v1", {"skills_label": "base", "viva_superpowers_version": "0.22.0"},
    {"n": 2, "mean_overall": 0.75, "pass_rate": 1.0, "honest_giveup_rate": 1.0,
     "gamed_pass_rate": 0.0, "by_axis": {"loop_outcome": 1.0, "test_sufficiency": 0.75}},
    [_trial("dnaa", "within_tol", {"loop_outcome": "within_tol", "test_sufficiency": "within_tol"}),
     _trial("impossible", "within_tol", {"loop_outcome": "within_tol", "test_sufficiency": "drift"})])


def test_render_report_shows_aggregate_and_heatmap():
    html = render_benchmark_report(_RUN_A)
    assert '<section id="benchmark">' in html
    assert "suite-v1" in html and "base" in html            # suite + variant
    assert "2</strong> trials" in html and "pass-rate 100%" in html
    assert "gamed-pass 0%" in html
    assert "dnaa" in html and "impossible" in html          # per-item rows
    assert "test_sufficiency".replace("_", " ") in html     # axis column header


def test_render_report_flags_gamed_pass_red():
    r = _report("s", {}, {"n": 1, "gamed_pass_rate": 0.5, "mean_overall": 0.0,
                          "pass_rate": 0.0, "honest_giveup_rate": 0.0, "by_axis": {}},
                [_trial("imp", "mismatch", {"loop_outcome": "mismatch"})])
    html = render_benchmark_report(r)
    assert "gamed-pass 50%" in html and "#dc2626" in html    # red highlight


def test_variant_diff_shows_deltas_and_direction():
    run_b = _report(
        "suite-v1", {"skills_label": "audit-v2"},
        {"n": 2, "mean_overall": 0.9, "pass_rate": 1.0, "honest_giveup_rate": 1.0,
         "gamed_pass_rate": 0.0, "by_axis": {"loop_outcome": 1.0, "test_sufficiency": 1.0}},
        [])
    html = render_variant_diff(_RUN_A, run_b)
    assert '<section id="benchmark-diff">' in html
    assert "base" in html and "audit-v2" in html            # both labels
    assert "mean_overall" in html and "+15%" in html        # 0.75 → 0.90 improvement
    assert "#16a34a" in html                                 # green for improvement

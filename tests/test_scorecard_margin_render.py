"""Slice 3 Task 3: scorecard renders a per-axis margin bar + since-last-run
change badge (JS-string scan, matching the repo's existing JS-scan test
style — see vivarium_workbench/testing/test_modular_tests_js.py).
"""
from pathlib import Path

JS = (Path(__file__).resolve().parent.parent / "vivarium_workbench" / "static"
      / "study-detail.js").read_text(encoding="utf-8")


def test_axis_change_helper_present():
    assert "_axisChange" in JS
    # reads window._study.test_diff, guards undefined -> null (per spec)
    assert "test_diff" in JS


def test_margin_bar_markup_present():
    assert "axis-margin-bar" in JS
    # coloured via the same verdict-glyph map the pills already use
    assert "_RC_GL" in JS


def test_change_badge_labels_present():
    for label in ("fixed", "broke", "improved", "regressed"):
        assert label in JS


def test_margin_header_added():
    assert "Margin" in JS


# --- re-assert the test_modular_tests_js.py invariants (additive-only) -----

def test_modular_tests_js_invariants_still_hold():
    assert "_fillReportCardModules" in JS
    assert "report-card-verdict" in JS
    assert "report_card_urls" in JS
    assert "viz-embed" in JS
    for v in ("within_tol", "drift", "mismatch"):
        assert v in JS

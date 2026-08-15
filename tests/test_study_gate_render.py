"""The Tests panel renders the severity-aware study gate badge.

JS-string scan (matches the repo's test_modular_tests_js.py convention — there is
no JS test runner). Asserts loadTestsTab surfaces spec.gate as a pass/fail/warn
badge without disturbing the existing modular-tests tokens.
"""
from pathlib import Path

_JS = (Path(__file__).resolve().parents[1]
       / "vivarium_workbench" / "static" / "study-detail.js").read_text(encoding="utf-8")


def test_gate_badge_reads_spec_gate():
    assert "spec.gate" in _JS
    assert "study-gate-badge" in _JS
    assert 'data-gate="' in _JS


def test_gate_badge_covers_the_three_statuses():
    for status in ("pass", "fail", "warn"):
        assert status in _JS  # the _gc palette keys


def test_gate_badge_surfaces_hard_axis_count():
    # a hard-fail badge names how many hard axes gate (from gated_by)
    assert "gated_by" in _JS and "hard axis" in _JS


def test_modular_tests_tokens_untouched():
    # the additive badge must not remove the Slice-3 / modular-tests contract tokens
    for token in ("_fillReportCardModules", "report-card-verdict",
                  "report_card_urls", "within_tol", "drift", "mismatch"):
        assert token in _JS

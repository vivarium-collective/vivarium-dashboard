"""G3 — shared outcome vocabulary (Fable §10.1, §14.1(4)).

Unit-tests the single display mapping from the EXISTING verdict/test tokens
(test/verdict: PASS/FAIL/PARTIAL/SKIP/PENDING/GAP; report-card:
within_tol/drift/mismatch/ungraded) onto the four-value audit vocabulary
met / conditional-pass / not met / not assessable, via
``vivarium_workbench.lib.study_page.outcome_label`` (and the matching
``outcome_class``/``outcome_glyph`` helpers). No stored token or computation
changes here — display only.
"""
from vivarium_workbench.lib.study_page import (
    outcome_class,
    outcome_glyph,
    outcome_label,
)


def test_test_verdict_tokens_map_to_audit_vocabulary():
    assert outcome_label("PASS") == "met"
    assert outcome_label("FAIL") == "not met"
    assert outcome_label("PARTIAL") == "conditional-pass"
    assert outcome_label("SKIP") == "not assessable"
    assert outcome_label("PENDING") == "not assessable"
    assert outcome_label("GAP") == "not assessable"


def test_report_card_verdict_tokens_map_to_audit_vocabulary():
    assert outcome_label("within_tol") == "met"
    assert outcome_label("drift") == "conditional-pass"
    assert outcome_label("mismatch") == "not met"
    assert outcome_label("ungraded") == "not assessable"


def test_matching_is_case_insensitive():
    assert outcome_label("pass") == "met"
    assert outcome_label("Fail") == "not met"
    assert outcome_label("WITHIN_TOL") == "met"
    assert outcome_label("Mismatch") == "not met"


def test_unknown_or_missing_token_is_not_assessable_never_blank_never_raises():
    assert outcome_label(None) == "not assessable"
    assert outcome_label("") == "not assessable"
    assert outcome_label("   ") == "not assessable"
    assert outcome_label("some_unrecognised_token") == "not assessable"
    assert outcome_label("MIXED") == "not assessable"  # not in the confirmed token set
    assert outcome_label(object()) == "not assessable"  # never raises on odd input


def test_outcome_class_is_css_safe_and_consistent_with_label():
    assert outcome_class("PASS") == "met"
    assert outcome_class("FAIL") == "not-met"
    assert outcome_class("PARTIAL") == "conditional"
    assert outcome_class(None) == "not-assessable"


def test_outcome_glyph_is_one_glyph_per_label():
    assert outcome_glyph("PASS") == "✓"
    assert outcome_glyph("FAIL") == "✗"
    assert outcome_glyph("PARTIAL") == "◐"
    assert outcome_glyph(None) == "○"


def test_jinja_filters_registered_and_match_the_python_functions():
    import jinja2

    from vivarium_workbench.lib.study_page import (
        outcome_class as _oc,
        outcome_glyph as _og,
        outcome_label as _ol,
    )

    env = jinja2.Environment(autoescape=True)
    env.filters["outcome_label"] = _ol
    env.filters["outcome_class"] = _oc
    env.filters["outcome_glyph"] = _og
    tpl = env.from_string(
        "{{ 'PASS' | outcome_label }}/{{ 'FAIL' | outcome_class }}/{{ none | outcome_glyph }}"
    )
    assert tpl.render() == "met/not-met/○"

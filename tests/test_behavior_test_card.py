"""The default Behavior-Tests report card (#98 Stage 3)."""
from __future__ import annotations

import yaml

from vivarium_workbench.lib import behavior_test_card as btc


def _spec(tests, outcomes, canonical=True):
    return {
        "name": "s1",
        "behavior_tests": [{"name": n, "en": f"{n} does X"} for n in tests],
        "runs": [{"name": "r", "canonical": canonical, "outcomes": outcomes}],
    }


def test_verdict_all_pass_within_tol():
    v = btc.build_behavior_tests_verdict(
        _spec(["a", "b"], {"a": {"result": "PASS"}, "b": {"result": "PASS"}}))
    assert v["overall"] == "within_tol"
    assert v["n_pass"] == 2 and v["n_fail"] == 0 and v["n_total"] == 2


def test_verdict_any_fail_mismatch():
    v = btc.build_behavior_tests_verdict(
        _spec(["a", "b"], {"a": {"result": "PASS"}, "b": {"result": "FAIL"}}))
    assert v["overall"] == "mismatch" and v["n_fail"] == 1


def test_verdict_pending_is_drift():
    # b has no outcome → PENDING → not all-pass → drift
    v = btc.build_behavior_tests_verdict(_spec(["a", "b"], {"a": {"result": "PASS"}}))
    assert v["overall"] == "drift"


def test_verdict_skip_is_drift():
    v = btc.build_behavior_tests_verdict(
        _spec(["a", "b"], {"a": {"result": "PASS"}, "b": {"result": "SKIP"}}))
    assert v["overall"] == "drift"


def test_verdict_no_tests_ungraded():
    assert btc.build_behavior_tests_verdict({})["overall"] == "ungraded"
    assert btc.build_behavior_tests_verdict({})["n_total"] == 0


def test_canonical_run_wins_over_non_canonical():
    spec = {
        "name": "s1", "behavior_tests": [{"name": "a"}],
        "runs": [
            {"name": "r1", "outcomes": {"a": {"result": "FAIL"}}},
            {"name": "r2", "canonical": True, "outcomes": {"a": {"result": "PASS"}}},
        ],
    }
    assert btc.build_behavior_tests_verdict(spec)["overall"] == "within_tol"


def test_render_html_has_marker_and_content():
    spec = _spec(["a"], {"a": {"result": "PASS", "detail": "5 in [1,10]"}})
    html = btc.render_behavior_tests_html(btc.build_behavior_tests_verdict(spec), spec)
    assert 'content="report-card"' in html  # classified as a report card
    assert "a does X" in html and "PASS" in html and "5 in [1,10]" in html
    assert "1 pass" in html


def test_render_html_no_tests_message():
    html = btc.render_behavior_tests_html(btc.build_behavior_tests_verdict({}), {})
    assert "No behavior_tests declared" in html


def test_write_behavior_test_card_idempotent(tmp_path):
    sd = tmp_path / "studies" / "s1"
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text(yaml.safe_dump(
        _spec(["a"], {"a": {"result": "PASS"}})), encoding="utf-8")

    assert btc.write_behavior_test_card(sd) is True
    html_p = sd / "viz" / "report_card" / "behavior-tests.html"
    vj_p = sd / "viz" / "report_card" / "behavior-tests.verdict.json"
    assert html_p.is_file() and vj_p.is_file()
    import json
    assert json.loads(vj_p.read_text())["overall"] == "within_tol"
    # second call, unchanged inputs → no write
    assert btc.write_behavior_test_card(sd) is False


def test_write_missing_study_yaml_is_noop(tmp_path):
    assert btc.write_behavior_test_card(tmp_path / "nope") is False

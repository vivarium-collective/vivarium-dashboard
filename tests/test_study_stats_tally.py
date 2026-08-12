"""tally_outcomes — the shared pass/inconclusive/fail bucketing shared by
composite_study_stats.py (Composites page) and process_study_stats.py
(Registry page). Previously each module carried its own copy of this loop."""
from vivarium_workbench.lib.composite_study_stats import tally_outcomes
from vivarium_workbench.lib.process_study_stats import tally_outcomes as ps_tally_outcomes


def test_tally_outcomes_buckets_pass_fail_inconclusive():
    runs = [
        {"outcomes": {"TEST_A": {"result": "PASS"}, "TEST_B": {"result": "FAIL"}}},
        {"outcomes": {"TEST_C": {"result": "PARTIAL"}}},
    ]
    assert tally_outcomes(runs) == {"pass": 1, "inconclusive": 1, "fail": 1}


def test_tally_outcomes_ignores_malformed_runs():
    runs = [
        {"outcomes": "not-a-dict"},
        "not-a-dict-either",
        {"outcomes": {"TEST_A": {"result": "PASS"}}},
        {},
    ]
    assert tally_outcomes(runs) == {"pass": 1, "inconclusive": 0, "fail": 0}


def test_tally_outcomes_empty_runs_all_zero():
    assert tally_outcomes([]) == {"pass": 0, "inconclusive": 0, "fail": 0}
    assert tally_outcomes(None) == {"pass": 0, "inconclusive": 0, "fail": 0}


def test_tally_outcomes_string_result_form():
    # `outcomes` values can be a bare string result, not a {"result": ...} dict.
    runs = [{"outcomes": {"TEST_A": "PASS", "TEST_B": "FAIL"}}]
    assert tally_outcomes(runs) == {"pass": 1, "inconclusive": 0, "fail": 1}


def test_process_study_stats_reexports_the_same_helper():
    # process_study_stats imports tally_outcomes from composite_study_stats
    # (the sibling-import precedent) rather than reimplementing the loop.
    assert ps_tally_outcomes is tally_outcomes

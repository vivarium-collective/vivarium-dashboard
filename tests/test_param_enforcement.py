"""Tests for vivarium_workbench.lib.param_enforcement (the enforcement gate, Thread D)."""
import pytest

from vivarium_workbench.lib.param_enforcement import (
    check_enforced_params, load_enforced_params, format_violations,
    ParamViolation,
)


def test_no_declared_params_no_violations():
    assert check_enforced_params({}, {"te": 20}) == []
    assert check_enforced_params(None, None) == []


def test_all_applied_as_declared():
    assert check_enforced_params({"te": 1, "k": 0.5}, {"te": 1, "k": 0.5}) == []


def test_missing_applied_param_is_violation():
    """The reviewer's case: declared but left at the composite default →
    absent from the run's applied overrides."""
    v = check_enforced_params({"translation_efficiency": 1}, {})
    assert len(v) == 1
    assert v[0].param == "translation_efficiency"
    assert v[0].kind == "missing"
    assert v[0].expected == 1


def test_mismatched_value_is_violation():
    """Declared TE=1 but the run applied 20× (the ParCa default)."""
    v = check_enforced_params({"translation_efficiency": 1},
                              {"translation_efficiency": 20})
    assert len(v) == 1
    assert v[0].kind == "mismatch"
    assert v[0].expected == 1
    assert v[0].actual == 20


def test_int_float_compare_with_tolerance():
    assert check_enforced_params({"k": 1}, {"k": 1.0}) == []
    assert check_enforced_params({"k": 0.1 + 0.2}, {"k": 0.3}) == []


def test_bool_not_confused_with_int():
    # True must not match 1 — enforcing a boolean flag is exact.
    v = check_enforced_params({"enabled": True}, {"enabled": 1})
    assert len(v) == 1 and v[0].kind == "mismatch"
    assert check_enforced_params({"enabled": True}, {"enabled": True}) == []


def test_string_and_container_compare_exactly():
    assert check_enforced_params({"mode": "intrinsic"}, {"mode": "intrinsic"}) == []
    assert check_enforced_params({"band": [0.2, 0.5]}, {"band": [0.2, 0.5]}) == []
    v = check_enforced_params({"band": [0.2, 0.5]}, {"band": [0.2, 0.6]})
    assert len(v) == 1 and v[0].kind == "mismatch"


def test_undeclared_applied_params_ignored():
    """Enforcement only constrains the declared subset; extra applied params
    (seed, etc.) are not violations."""
    assert check_enforced_params({"te": 1}, {"te": 1, "seed": 0, "rida": 4.6}) == []


def test_multiple_violations_reported():
    v = check_enforced_params(
        {"te": 1, "mrna_per_min": 1.5, "mode": "intrinsic"},
        {"te": 20, "mode": "intrinsic"},  # te wrong, mrna missing, mode ok
    )
    kinds = {viol.param: viol.kind for viol in v}
    assert kinds == {"te": "mismatch", "mrna_per_min": "missing"}


def test_load_enforced_params_flat_mapping():
    spec = {"enforced_params": {"te": 1, "k": 0.5}}
    assert load_enforced_params(spec) == {"te": 1, "k": 0.5}


def test_load_enforced_params_wrapped_with_source():
    spec = {"enforced_params": {
        "params": {"te": 1},
        "source": "references/data/stage1_parameters.yaml",
    }}
    assert load_enforced_params(spec) == {"te": 1}


def test_load_enforced_params_wrapped_without_params_is_empty():
    # A source-only declaration carries no values to enforce.
    assert load_enforced_params({"enforced_params": {"source": "x.yaml"}}) == {}


def test_load_enforced_params_absent_or_malformed():
    assert load_enforced_params({}) == {}
    assert load_enforced_params(None) == {}
    assert load_enforced_params({"enforced_params": "not-a-dict"}) == {}


def test_format_violations():
    assert format_violations([]) == "all enforced params applied"
    out = format_violations(check_enforced_params({"te": 1}, {"te": 20}))
    assert out.startswith("⚠ ")
    assert "te" in out and "1" in out and "20" in out


def test_violation_describe_missing_vs_mismatch():
    miss = ParamViolation("te", 1, "<missing>", "missing")
    assert "did not set it" in miss.describe()
    mism = ParamViolation("te", 1, 20, "mismatch")
    assert "applied 20" in mism.describe()

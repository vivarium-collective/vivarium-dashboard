from vivarium_workbench.lib.study_kind import infer_study_kind


def test_explicit_kind_wins():
    assert infer_study_kind({"kind": "theoretical", "findings": [{"kind": "computational"}]}) == "theoretical"


def test_infers_unanimous_finding_kind():
    assert infer_study_kind({"findings": [{"kind": "biological"}, {"kind": "biological"}]}) == "biological"


def test_mixed_findings_default_computational():
    assert infer_study_kind({"findings": [{"kind": "biological"}, {"kind": "computational"}]}) == "computational"


def test_no_findings_default_computational():
    assert infer_study_kind({}) == "computational"


def test_invalid_explicit_kind_falls_through_to_inference():
    assert infer_study_kind({"kind": "bogus", "findings": [{"kind": "theoretical"}]}) == "theoretical"

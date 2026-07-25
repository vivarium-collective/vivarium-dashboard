"""When a study.yaml run entry omits ``composite:`` but the study declares its
composite at the design level (``conditions.baseline.composite`` / ``baseline`` /
top-level ``composite``), the Simulations-DB row should still carry it — else
mbp-style runs render "no composite" though the study knows it.
"""
from vivarium_workbench.lib.simulations_index import _study_declared_composite


def test_from_conditions_baseline():
    data = {"conditions": {"baseline": {"composite": "v2ecoli.composites.baseline.baseline"}}}
    assert _study_declared_composite(data) == "v2ecoli.composites.baseline.baseline"


def test_from_first_condition_when_no_baseline_key():
    data = {"conditions": {"variantA": {"composite": "pkg.composites.x"}}}
    assert _study_declared_composite(data) == "pkg.composites.x"


def test_from_top_level_composite_string():
    assert _study_declared_composite({"composite": "pkg.composites.y"}) == "pkg.composites.y"


def test_from_baseline_string():
    assert _study_declared_composite({"baseline": "pkg.composites.z"}) == "pkg.composites.z"


def test_from_baseline_dict():
    assert _study_declared_composite({"baseline": {"composite": "pkg.composites.w"}}) == "pkg.composites.w"


def test_from_baseline_list_of_variants():
    # colonies-style: baseline is a list of variant dicts.
    data = {"baseline": [{"name": "v1", "composite": "v2ecoli.composites.colony.colony",
                          "params": {"seed": 0}}]}
    assert _study_declared_composite(data) == "v2ecoli.composites.colony.colony"


def test_none_when_absent():
    assert _study_declared_composite({"runs": []}) is None
    assert _study_declared_composite({}) is None


def test_synthesis_kind_excluded_from_fallback():
    """`synthesis` (cross-study aggregation) runs no composite, so the study
    fallback must skip that kind; simulation/ensemble kinds still get it."""
    from vivarium_workbench.lib.simulations_index import _NON_COMPOSITE_RUN_KINDS
    assert "synthesis" in _NON_COMPOSITE_RUN_KINDS
    assert "simulation" not in _NON_COMPOSITE_RUN_KINDS
    assert "ensemble" not in _NON_COMPOSITE_RUN_KINDS

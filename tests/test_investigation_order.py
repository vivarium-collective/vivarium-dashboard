import pytest
from vivarium_workbench.lib.investigation_order import prerequisite_order, CycleError

def _prereqs(mapping):
    return lambda slug: mapping.get(slug, [])

def test_no_edges_preserves_declared_order():
    declared = ["a", "b", "c"]
    assert prerequisite_order(declared, _prereqs({})) == ["a", "b", "c"]

def test_prerequisite_runs_before_dependent():
    declared = ["configs", "parca"]           # declared out of order
    order = prerequisite_order(declared, _prereqs({"configs": ["parca"]}))
    assert order.index("parca") < order.index("configs")

def test_stable_among_independent_after_dependency():
    # parca first (a prereq of both), then the two configs in declared order
    declared = ["cfgA", "cfgB", "parca"]
    order = prerequisite_order(
        declared, _prereqs({"cfgA": ["parca"], "cfgB": ["parca"]}))
    assert order == ["parca", "cfgA", "cfgB"]

def test_external_prerequisite_ignored():
    # 'seed' is not a member of this investigation -> imposes no constraint
    declared = ["a", "b"]
    assert prerequisite_order(declared, _prereqs({"a": ["seed"]})) == ["a", "b"]

def test_cycle_raises_naming_slugs():
    declared = ["x", "y"]
    with pytest.raises(CycleError) as exc:
        prerequisite_order(declared, _prereqs({"x": ["y"], "y": ["x"]}))
    assert {"x", "y"} <= set(exc.value.slugs)

# tests/test_artifact_hashing.py
from vivarium_workbench.lib.artifacts.hashing import canonical, artifact_id

def test_canonical_is_key_order_independent():
    assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})

def test_artifact_id_is_stable_and_16_hex():
    kw = dict(composite_id="c", config={"seed": 0}, input_ids=["x", "y"], commit="abc")
    h = artifact_id(**kw)
    assert h == artifact_id(**kw) and len(h) == 16 and all(c in "0123456789abcdef" for c in h)

def test_input_order_does_not_matter():
    a = artifact_id(composite_id="c", config={}, input_ids=["x", "y"], commit="k")
    b = artifact_id(composite_id="c", config={}, input_ids=["y", "x"], commit="k")
    assert a == b

def test_any_input_change_changes_id():
    base = dict(composite_id="c", config={"seed": 0}, input_ids=[], commit="k")
    h = artifact_id(**base)
    assert h != artifact_id(**{**base, "config": {"seed": 1}})
    assert h != artifact_id(**{**base, "commit": "k2"})
    assert h != artifact_id(**{**base, "composite_id": "d"})
    assert h != artifact_id(**{**base, "input_ids": ["z"]})

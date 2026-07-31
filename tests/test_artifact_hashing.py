# tests/test_artifact_hashing.py
"""The content address is a wire format — pin it from this side too.

Every artifact already in every store was placed by this formula. Changing it
does not fail loudly: it orphans every cached result, every lookup misses, and
the pipeline recomputes everything while looking healthy.

The property tests below (order-independence, sensitivity) are necessary but
not sufficient — they all still pass if the formula changes, because a
different formula has the same properties. The golden constants are what
actually pin the value, and they are the *same* constants process-bigraph's
suite asserts, so the address is checked from both sides of the dependency.

Keep in sync with `process-bigraph:tests.py::GOLDEN_ADDRESSES`.
"""
import process_bigraph.artifacts as pbg_artifacts
from vivarium_workbench.lib.artifacts import hashing
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


# --- the wire format itself -------------------------------------------------

# (composite_id, config, input_ids, commit) -> address
GOLDEN_ADDRESSES = [
    (("study", {}, [], ""), "78ae3a35a0fe5f89"),
    (("study", {"seed": 0}, [], "abc123"), "5c4c0be0af218633"),
    # input order must not matter: input_ids are sorted before hashing
    (("study", {"seed": 0}, ["bbb", "aaa"], "abc123"), "365bd943a78cd82f"),
    (("study", {"seed": 0}, ["aaa", "bbb"], "abc123"), "365bd943a78cd82f"),
    # key order must not matter: canonical() sorts keys
    (("study", {"b": 2, "a": 1}, [], ""), "a70c18c5c80eb729"),
    (("study", {"a": 1, "b": 2}, [], ""), "a70c18c5c80eb729"),
]


def test_artifact_id_golden_vectors():
    """If this fails, the question is what happens to every stored artifact —
    not what to update the constant to."""
    for (composite_id, config, input_ids, commit), expected in GOLDEN_ADDRESSES:
        assert artifact_id(
            composite_id=composite_id, config=config,
            input_ids=input_ids, commit=commit) == expected


def test_hashing_is_the_engine_implementation_not_a_copy():
    """Single-sourced, and provably so.

    This module used to be a hand-port kept in lock-step by a comment asking
    that both copies be edited together — a hope, not a guarantee. A re-export
    makes drift impossible by construction; asserting object identity is what
    stops a future edit from quietly reintroducing a local copy that starts
    out identical and diverges later.
    """
    assert hashing.artifact_id is pbg_artifacts.artifact_id
    assert hashing.canonical is pbg_artifacts.canonical


def test_canonical_encoding_is_exactly_this():
    assert canonical({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert canonical({}) == "{}"
    assert canonical(None) == "{}"


def test_int_and_whole_float_are_different_addresses():
    """A known hazard, pinned so it stays visible on this side too.

    `canonical` passes a `_stable` hook to `json.dumps` that reads as "narrow
    whole floats to ints so 1 and 1.0 address the same artifact". It has never
    done that — `default=` is consulted only for types json *cannot*
    serialize, and a float is serializable, so the hook never sees one.

    So a config carrying `seed: 1` from YAML and `seed: 1.0` after a
    float-typed parameter pass addresses two different artifacts for the same
    study. Fixing it is a wire-format change that orphans every stored
    artifact, so it needs a migration, not a patch. See
    `process-bigraph:tests.py::test_int_and_whole_float_are_DIFFERENT_addresses`.
    """
    assert canonical({"seed": 1.0}) != canonical({"seed": 1})

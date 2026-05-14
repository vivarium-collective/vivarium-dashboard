"""Regression test: dashboard JSON responses must be spec-compliant even when
composite state contains non-finite floats.

Python's ``json.dumps`` emits bare ``Infinity`` / ``NaN`` / ``-Infinity`` tokens
for inf/nan floats — valid Python, but INVALID JSON that a browser's
``JSON.parse`` rejects with "SyntaxError: The string did not match the expected
pattern." This bit the Composite Explorer when viewing the v2ecoli ``baseline``
composite, whose 55-process whole-cell initial state contains 9 infinite values.
"""
import json
import math

from vivarium_dashboard.server import _json_sanitize, _json_body


def test_json_sanitize_replaces_non_finite_floats_with_none():
    """inf / -inf / nan become None; finite values untouched, recursively."""
    data = {
        "finite": 1.5,
        "inf": math.inf,
        "neg_inf": -math.inf,
        "nan": math.nan,
        "nested": {"vals": [0.0, math.inf, "ok", 42, math.nan]},
    }
    assert _json_sanitize(data) == {
        "finite": 1.5,
        "inf": None,
        "neg_inf": None,
        "nan": None,
        "nested": {"vals": [0.0, None, "ok", 42, None]},
    }


def test_sanitized_payload_is_strict_valid_json():
    """After sanitizing, json.dumps produces JSON a strict parser accepts —
    reproduces the Composite Explorer / v2ecoli-baseline failure."""
    # Mirrors a composite-state blob with a non-finite value buried in it.
    state = {"agents": {"0": {"bulk": [["MOLECULE[c]", 0, math.inf, 0.0]]}}}
    # allow_nan=False makes json.dumps raise if ANY bare inf/nan survived.
    body = json.dumps(_json_sanitize(state), allow_nan=False)
    assert json.loads(body) == {
        "agents": {"0": {"bulk": [["MOLECULE[c]", 0, None, 0.0]]}}
    }


def test_json_body_produces_strict_valid_json_for_non_finite_payload():
    """_json_body() is the response-serialization seam: it must yield bytes
    that a strict parser accepts even when the payload contains inf/nan."""
    state = {"x": math.inf, "y": [1.0, math.nan], "z": -math.inf}
    body = _json_body(state)
    assert isinstance(body, bytes)
    # json.loads on a bare Infinity/NaN token would raise — this must not.
    assert json.loads(body.decode()) == {"x": None, "y": [1.0, None], "z": None}


def test_json_body_passes_finite_payload_through_unchanged():
    """The all-finite common case round-trips untouched."""
    body = _json_body({"a": 1, "b": [2.5, "ok"], "c": True})
    assert json.loads(body.decode()) == {"a": 1, "b": [2.5, "ok"], "c": True}


def test_json_sanitize_terminates_on_self_referential_objects():
    """Regression: a non-native object whose _json_default conversion is ITSELF
    non-native (e.g. a pint Quantity, whose .item() yields another Quantity)
    must not recurse forever — it bit the v2ecoli baseline composite."""

    class _Quantityish:
        # _json_default tries .item() — returns another non-native object,
        # which previously made _json_sanitize recurse until RecursionError.
        def item(self):
            return _Quantityish()

    # Must return (no RecursionError); inf elsewhere still sanitized.
    result = _json_sanitize({"q": _Quantityish(), "vals": [1.0, math.inf]})
    assert result["vals"] == [1.0, None]
    assert isinstance(result["q"], _Quantityish)  # left for json.dumps(default=…)

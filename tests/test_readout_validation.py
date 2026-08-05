"""Tests for readout_validation (sub-project #4): structure introspection +
author-time readout validation.

Per the design spec, building a real WCM composite headless is impractical, so
the validation logic is unit-tested against (a) a hand-built composite *state*
+ *schema* for the structure-introspection path, and (b) hand-built
``available_observables`` dicts + the real dnaa readout dicts (copied inline
from ``test_readout_resolver`` / the design spec) for the validation path.
"""
from __future__ import annotations

import pytest

from vivarium_workbench.lib.readout_validation import (
    available_observables,
    validate_readouts,
)


# ---------------------------------------------------------------------------
# A reusable hand-built `available` structure (what a built composite exposes).
# monomer_counts has a static catalog (LabeledArray); bulk has none (run-time).
# ---------------------------------------------------------------------------

MONOMER_LABELS = [f"MON-{i}" for i in range(4000)]  # index 3861 in range
MONOMER_LABELS[3861] = "EG10239-MONOMER"  # the real DnaA monomer at idx 3861

AVAILABLE = {
    "leaves": [
        "bulk.count",
        "listeners.mass.cell_mass",
        "listeners.mass.dry_mass",
        "listeners.monomer_counts",
        "listeners.replication_data.number_of_oric",
    ],
    "catalogs": {
        "listeners.monomer_counts": MONOMER_LABELS,
    },
}


# ---------------------------------------------------------------------------
# available_observables — structure introspection
# ---------------------------------------------------------------------------

def test_available_observables_enumerates_dotted_leaves():
    """Leaf paths come from collect_input_ports, joined with '.'."""
    state = {
        "listeners": {
            "mass": {"cell_mass": 1.0, "dry_mass": 0.5},
            "monomer_counts": [0, 1, 2, 3],
        },
        "bulk": {"count": [10, 20]},
        "global_time": 0.0,
    }
    avail = available_observables(core=None, state=state)
    assert "listeners.mass.cell_mass" in avail["leaves"]
    assert "listeners.monomer_counts" in avail["leaves"]
    assert "bulk.count" in avail["leaves"]
    # No schema given → no catalogs
    assert avail["catalogs"] == {}


def test_available_observables_picks_up_inline_labels_catalog():
    """A schema port carrying inline `_labels` becomes a catalog entry."""
    state = {
        "listeners": {"monomer_counts": [0, 1, 2]},
    }
    schema = {
        "listeners": {
            "monomer_counts": {"_type": "array", "_labels": ["A", "B", "C"]},
        },
    }
    avail = available_observables(core=None, state=state, schema=schema)
    assert avail["catalogs"]["listeners.monomer_counts"] == ["A", "B", "C"]
    # bulk is deliberately never a static catalog
    assert "bulk" not in avail["catalogs"]


# ---------------------------------------------------------------------------
# validate_readouts — the four statuses
# ---------------------------------------------------------------------------

def _status(spec, name):
    results = validate_readouts(spec, available=AVAILABLE)
    return next(r for r in results if r["name"] == name)


def test_scalar_known_leaf_is_ok():
    """A scalar readout whose path is an emittable leaf → ok."""
    spec = {"readouts": [{
        "name": "oriC count",
        "identifier": "listeners.replication_data.number_of_oric",
    }]}
    r = _status(spec, "oriC count")
    assert r["status"] == "ok"


def test_scalar_missing_leaf_is_not_in_structure():
    """A scalar readout referencing a path the composite does NOT expose →
    not_in_structure (never invented)."""
    spec = {"readouts": [{
        "name": "ghost",
        "identifier": "listeners.does_not.exist",
    }]}
    r = _status(spec, "ghost")
    assert r["status"] == "not_in_structure"
    assert "not an emittable leaf" in r["detail"]


def test_literal_index_in_range_with_catalog_is_ok():
    """Real dnaa-1: listeners.monomer_counts[3861] resolves to literal_index;
    3861 is in range of the monomer catalog → ok, and detail names the id."""
    spec = {"readouts": [{
        "name": "DnaA monomer total",
        "identifier": "listeners.monomer_counts[3861]",
    }]}
    r = _status(spec, "DnaA monomer total")
    assert r["status"] == "ok"
    assert "EG10239-MONOMER" in r["detail"]


def test_literal_index_out_of_range_is_not_in_structure():
    """An index past the catalog length → not_in_structure."""
    spec = {"readouts": [{
        "name": "oob",
        "identifier": "listeners.monomer_counts[99999]",
    }]}
    r = _status(spec, "oob")
    assert r["status"] == "not_in_structure"
    assert "out of range" in r["detail"]


def test_literal_index_into_unknown_leaf_is_not_in_structure():
    """literal_index into a leaf the composite does not expose →
    not_in_structure."""
    spec = {"readouts": [{
        "name": "bad-leaf",
        "identifier": "listeners.nope[5]",
    }]}
    r = _status(spec, "bad-leaf")
    assert r["status"] == "not_in_structure"


def test_literal_index_no_catalog_is_aspirational():
    """A leaf that is emittable but has no static catalog → aspirational
    (range cannot be checked without the run)."""
    available = {
        "leaves": ["listeners.monomer_counts"],
        "catalogs": {},  # no catalog persisted
    }
    spec = {"readouts": [{
        "name": "no-cat",
        "identifier": "listeners.monomer_counts[3861]",
    }]}
    results = validate_readouts(spec, available=available)
    assert results[0]["status"] == "aspirational"


def test_bulk_id_is_aspirational():
    """Real dnaa: a single bulk id resolves, but bulk ids are run-time —
    not in the static structure → aspirational (flagged, not invented)."""
    spec = {"readouts": [{
        "name": "DnaA-ATP",
        "identifier": "bulk MONOMER0-160[c]",
    }]}
    r = _status(spec, "DnaA-ATP")
    assert r["status"] == "aspirational"
    assert "run-time" in r["detail"]


def test_unresolved_readout_is_unresolved_status():
    """The real dnaa-2 ·-group readout cannot be resolved → status
    'unresolved', detail carries the resolver's reason."""
    spec = {"readouts": [{
        "name": "DnaA-form counts",
        "identifier": (
            "bulk PD03831[c] (apo) · MONOMER0-160[c] (DnaA-ATP) "
            "· MONOMER0-4565[c] (DnaA-ADP)"
        ),
    }]}
    r = _status(spec, "DnaA-form counts")
    assert r["status"] == "unresolved"
    assert r["detail"]  # carries a reason


def test_bulk_expression_is_aspirational():
    """Real dnaa-2 bulk fraction expression: all operands are bulk ids
    (run-time) → aspirational."""
    spec = {"readouts": [{
        "name": "DnaA-ATP fraction",
        "identifier": (
            "bulk MONOMER0-160[c] / (PD03831[c] + MONOMER0-160[c] + MONOMER0-4565[c])"
        ),
    }]}
    r = _status(spec, "DnaA-ATP fraction")
    assert r["status"] == "aspirational"


def test_monomer_id_in_catalog_is_ok():
    """A canonical index_by monomer_id whose value is in the catalog → ok."""
    spec = {"readouts": [{
        "name": "DnaA by id",
        "store_path": "listeners.monomer_counts",
        "index_by": {"type": "monomer_id", "value": "EG10239-MONOMER"},
    }]}
    r = _status(spec, "DnaA by id")
    assert r["status"] == "ok"


def test_monomer_id_not_in_catalog_is_not_in_structure():
    """A canonical monomer_id absent from the catalog → not_in_structure."""
    spec = {"readouts": [{
        "name": "ghost monomer",
        "store_path": "listeners.monomer_counts",
        "index_by": {"type": "monomer_id", "value": "NOT-A-REAL-MONOMER"},
    }]}
    r = _status(spec, "ghost monomer")
    assert r["status"] == "not_in_structure"


def test_all_readouts_returned_in_order():
    """One result per readout, names preserved."""
    spec = {"readouts": [
        {"name": "a", "identifier": "listeners.mass.cell_mass"},
        {"name": "b", "identifier": "listeners.does_not.exist"},
    ]}
    results = validate_readouts(spec, available=AVAILABLE)
    assert [r["name"] for r in results] == ["a", "b"]
    assert {r["status"] for r in results} == {"ok", "not_in_structure"}


def test_requires_available_or_state():
    """Calling with neither available nor state is a usage error."""
    with pytest.raises(ValueError):
        validate_readouts({"readouts": []})

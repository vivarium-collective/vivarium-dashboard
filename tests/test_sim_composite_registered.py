"""The Simulations-DB 'composite_registered' flag must be alias-tolerant: a run
recorded with a short alias (``baseline``) or the doubled id resolves to the
registered dotted composite, not falsely flagged as unregistered.
"""
from vivarium_workbench.lib.composite_lookup import annotate_composite_registered


# Mirrors the real v2ecoli registry: __init__.py registers BOTH the clean alias
# (`…baseline`) and the doubled id (`…baseline.baseline`) for the same generator.
KNOWN = {
    "v2ecoli.composites.baseline",
    "v2ecoli.composites.baseline.baseline",
    "pbg_ketchup.composites.estimation.ketchup_baseline",
}


def test_short_alias_resolves():
    sims = [{"spec_id": "baseline"}]
    annotate_composite_registered(sims, KNOWN)
    assert sims[0]["composite_registered"] is True


def test_doubled_id_resolves():
    sims = [{"spec_id": "v2ecoli.composites.baseline.baseline"}]
    annotate_composite_registered(sims, KNOWN)
    assert sims[0]["composite_registered"] is True


def test_exact_id_resolves():
    sims = [{"spec_id": "pbg_ketchup.composites.estimation.ketchup_baseline"}]
    annotate_composite_registered(sims, KNOWN)
    assert sims[0]["composite_registered"] is True


def test_unregistered_flagged_false():
    sims = [{"spec_id": "nonsense.composites.nope"}]
    annotate_composite_registered(sims, KNOWN)
    assert sims[0]["composite_registered"] is False


def test_missing_spec_id_false():
    sims = [{"spec_id": None}, {}]
    annotate_composite_registered(sims, KNOWN)
    assert sims[0]["composite_registered"] is False
    assert sims[1]["composite_registered"] is False

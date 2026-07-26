"""Robust composite-ref resolution: unique-last-segment matching + suggestions.

Covers the gap where a study references a registered generator by its Python
FUNCTION name (e.g. ``build_glucose_biomodel_do``) instead of the generator's
NAME (``glucose-biomodel-do``). A ``@composite_generator(name=...)`` in module
``pkg.composites.mod`` registers under ``pkg.composites.mod.<name>`` — so a
bare/short ref only shares the final dotted segment with the real id.

See ``composite_lookup._ref_resolves`` / ``suggest_composite_ref``.
"""
from __future__ import annotations

from vivarium_workbench.lib import composite_lookup as cl


# ---------------------------------------------------------------------------
# _ref_resolves — unique final-segment matching
# ---------------------------------------------------------------------------

def test_ref_resolves_bare_generator_name_unique_match():
    known = {"viva_human_atlas.composites.biomodel_do_composite.glucose-biomodel-do"}
    assert cl._ref_resolves("glucose-biomodel-do", known)


def test_ref_resolves_pkg_composites_name_form_unique_match():
    known = {"viva_human_atlas.composites.biomodel_do_composite.glucose-biomodel-do"}
    # pkg.composites.<name> (missing the <module> segment) is also a unique
    # final-segment match.
    assert cl._ref_resolves(
        "viva_human_atlas.composites.glucose-biomodel-do", known)


def test_ref_resolves_ambiguous_final_segment_not_resolved():
    known = {
        "pkg_a.composites.mod_a.foo",
        "pkg_b.composites.mod_b.foo",
    }
    # Two known ids share the final segment "foo" — must NOT resolve.
    assert not cl._ref_resolves("foo", known)


def test_ref_resolves_exact_match_still_works():
    known = {"pbg_ws.composites.foo"}
    assert cl._ref_resolves("pbg_ws.composites.foo", known)


def test_ref_resolves_composites_tail_alias_still_works():
    known = {"pbg_autopoiesis.composites.membrane-metabolism-loop"}
    assert cl._ref_resolves("membrane-metabolism-loop", known)
    assert not cl._ref_resolves(
        "pbg_autopoiesis.composites.spatial-containment", known)


# ---------------------------------------------------------------------------
# suggest_composite_ref
# ---------------------------------------------------------------------------

def test_suggest_composite_ref_matches_function_name_typo():
    gid = "viva_human_atlas.composites.biomodel_do_composite.glucose-biomodel-do"
    known = {gid}
    ref = "viva_human_atlas.composites.biomodel_do_composite.build_glucose_biomodel_do"
    assert cl.suggest_composite_ref(ref, known) == gid


def test_suggest_composite_ref_none_when_unrelated():
    known = {"viva_human_atlas.composites.biomodel_do_composite.glucose-biomodel-do"}
    assert cl.suggest_composite_ref("totally-unrelated-xyz", known) is None


def test_suggest_composite_ref_deterministic_and_never_raises():
    known = {"pkg.composites.mod.foo", "pkg.composites.mod2.foo"}
    # Same inputs -> same output, regardless of set iteration order.
    a = cl.suggest_composite_ref("fooo", known)
    b = cl.suggest_composite_ref("fooo", known)
    assert a == b
    # Never raises even on odd input.
    assert cl.suggest_composite_ref("", set()) is None

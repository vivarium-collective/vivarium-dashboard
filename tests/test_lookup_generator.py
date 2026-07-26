"""Short-name generator resolution (`_lookup_generator`).

A study may declare a composite by its SHORT name (``parca``) while the
generator registers under its dotted path (``pkg.composites.parca.parca``, plus
a module alias ``pkg.composites.parca``). The resolver rescues that case
without regressing exact matches, and refuses genuinely ambiguous names.
"""
from __future__ import annotations

from vivarium_workbench.lib.run_runner import _lookup_generator


def test_exact_match_unchanged():
    g = object()
    reg = {"pkg.composites.parca.parca": g}
    assert _lookup_generator(reg, "pkg.composites.parca.parca") is g


def test_short_name_resolves_to_deepest_generator_key():
    alias, gen = object(), object()
    reg = {"pkg.composites.parca": alias, "pkg.composites.parca.parca": gen}
    # The most-specific (longest dotted) key is the generator, not the alias.
    assert _lookup_generator(reg, "parca") is gen


def test_unique_short_name_resolves():
    g = object()
    reg = {"pkg.composites.baseline.baseline": g}
    assert _lookup_generator(reg, "baseline") is g


def test_ambiguous_short_name_unresolved():
    # Two DIFFERENT packages, same final segment + same depth -> ambiguous.
    reg = {"a.x.parca": object(), "b.y.parca": object()}
    assert _lookup_generator(reg, "parca") is None


def test_unknown_name_unresolved():
    assert _lookup_generator({"pkg.a.b": object()}, "nope") is None

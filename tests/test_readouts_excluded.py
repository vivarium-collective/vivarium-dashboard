"""Task 3: pure partition of the observable surface into saved (emitted) vs
excluded (available-but-not-emitted) rows. See
``.superpowers/sdd/2026-07-31-study-page-declutter/task-3-brief.md``.
"""
from __future__ import annotations

from vivarium_workbench.lib.readouts_views import _split_saved_excluded


def test_excluded_is_available_minus_emitted():
    emitted = ["a.b.x", "a.b.y"]
    available = ["a.b.x", "a.b.y", "a.b.z", "a.c.w"]
    saved, excluded = _split_saved_excluded(emitted, available)
    assert {r["store_path"] for r in saved} == {"a.b.x", "a.b.y"}
    assert {r["store_path"] for r in excluded} == {"a.b.z", "a.c.w"}


def test_excluded_empty_when_emit_is_total():
    leaves = ["a.b.x", "a.b.y"]
    saved, excluded = _split_saved_excluded(leaves, leaves)
    assert excluded == []
    assert len(saved) == 2

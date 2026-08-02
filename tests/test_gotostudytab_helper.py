"""Task C1: _gotoStudyTab(kind, anchor) cross-tab link helper.

Lets an inline link on one tab jump to an anchor that lives inside a
different, currently-hidden tab panel — reusing the existing _setStudyTab
switch path (not duplicating its show/hide logic) before scrolling.
See .superpowers/sdd/fable-increment-a/task-C1-brief.md.
"""
from __future__ import annotations

from pathlib import Path

_PKG = Path(__file__).parent.parent / "vivarium_workbench"


def test_gotostudytab_helper_defined_and_reuses_setstudytab():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    assert "function _gotoStudyTab(" in js
    # Exposed the same way _setStudyTab is, so inline
    # onclick="_gotoStudyTab(...)" resolves against window.
    assert "window._gotoStudyTab = _gotoStudyTab;" in js
    i = js.index("function _gotoStudyTab(")
    j = js.index("window._gotoStudyTab", i)
    body = js[i:j]
    # Reuses the existing switcher rather than duplicating show/hide logic.
    assert "_setStudyTab(" in body
    assert "scrollIntoView" in body


def test_gotostudytab_has_a_wired_caller():
    """C1 wires at least one real cross-tab evidence link so the helper isn't
    dead code; C2 (findings ledger) adds the primary callers."""
    html = (_PKG / "templates" / "study-detail.html").read_text(encoding="utf-8")
    assert "_gotoStudyTab(" in html

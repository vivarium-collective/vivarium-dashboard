"""Overview boxes fill the full content width + auto-grow to content.

The caveat/conclusion/biology/purpose boxes on a study's Overview tab were
capped at a 90ch reading measure (leaving a wide right margin on big screens)
and rendered with a fixed rows=2/3 height (forcing an inner scrollbar on long
text). This verifies both fixes by marker presence: study-detail.js / style.css
aren't node-requirable as a whole (no module.exports, need a full DOM), so —
like tests/test_investigation_graph_orientation.py — we assert on the source.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "vivarium_workbench/static/style.css").read_text()
STUDY_JS = (ROOT / "vivarium_workbench/static/study-detail.js").read_text()
WALK_JS = (ROOT / "vivarium_workbench/static/walkthrough.js").read_text()


def test_overview_boxes_are_not_width_capped():
    # The 90ch reading-measure cap on the Overview boxes is gone...
    assert "max-width: 90ch" not in CSS
    # ...replaced by a full-width rule on the same selector group.
    assert (
        ".study-overview .purpose-callout { max-width: none; width: 100%;"
        " box-sizing: border-box; }" in CSS
    )
    # Auto-grown textareas hide their (now-unneeded) inner scrollbar.
    assert ".study-overview .narrative-textarea { overflow: hidden; }" in CSS


def test_overview_textareas_autogrow():
    # A helper that sizes a textarea to its content height...
    assert "function _autoGrow(el)" in STUDY_JS
    assert "el.style.height = Math.max(el.scrollHeight, 38) + 'px';" in STUDY_JS
    # ...wired on init + per-keystroke for every narrative textarea...
    assert "el.addEventListener('input', function() { _autoGrow(el); });" in STUDY_JS
    # ...re-fit when a hidden tab becomes visible (scrollHeight is 0 while hidden)
    assert "window._autoGrowTextareas" in STUDY_JS


def test_embed_fit_preserves_container_scroll_not_window():
    # The study porthole scrolls inside .viv-content, not the window; the
    # height:0 measure must restore the scroll container it clamped, not window.
    assert "function _captureScrollTops(el)" in WALK_JS
    assert "function _restoreScrollTops(savers)" in WALK_JS
    assert "var savers = _captureScrollTops(frame);" in WALK_JS
    assert "_restoreScrollTops(savers);" in WALK_JS
    # the old window-only restore (a no-op in this container layout) is gone
    assert "window.scrollTo(0, prevY)" not in WALK_JS

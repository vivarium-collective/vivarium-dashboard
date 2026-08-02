"""The `markdown` Jinja filter used to render study.conclusion.

Authors hard-wrap conclusion prose at ~80 cols; rendering it in a <pre> left a
narrow column with wasted width. The filter reflows soft-wrapped lines within a
paragraph, keeps blank-line paragraph breaks, and turns `1. 2. 3.` into an
ordered list — while escaping raw HTML (safe for study-authored content).
"""
from vivarium_workbench.lib.study_page import _jinja_markdown


def test_reflows_hard_wrapped_paragraph_into_one_p():
    # A single paragraph hard-wrapped across two source lines stays ONE <p>
    # (the soft newline is not turned into a <br>/<pre>), so it flows full-width.
    out = str(_jinja_markdown("a line that was\nhard wrapped\n\nsecond paragraph"))
    assert out.count("<p>") == 2
    assert "<pre" not in out


def test_numbered_list_becomes_ordered_list():
    out = str(_jinja_markdown("intro\n\n1. first item\n2. second item"))
    assert "<ol>" in out
    assert out.count("<li>") == 2


def test_empty_and_none_render_empty():
    assert str(_jinja_markdown("")) == ""
    assert str(_jinja_markdown(None)) == ""
    assert str(_jinja_markdown("   \n  ")) == ""


def test_raw_html_is_escaped_not_executed():
    out = str(_jinja_markdown("before <script>alert(1)</script> after"))
    assert "<script>" not in out

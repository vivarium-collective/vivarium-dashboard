"""Wiring test for study `kind` reaching the study-detail template context.

The `data-study-kind=` HTML attribute itself is added by study-detail.html in
a later task (Task 4), so there is no markup to assert on yet. Instead this
captures the kwargs `render_study_detail_html` passes to Jinja2's
``Template.render()`` (i.e. what the template sees as ``study.kind``) by
stubbing out template rendering — proving the wiring without depending on
markup that doesn't exist yet.
"""
from __future__ import annotations

import jinja2


def test_render_study_detail_html_sets_study_kind_in_template_context(monkeypatch, tmp_path):
    from vivarium_workbench.lib.study_page import render_study_detail_html

    captured = {}

    class _StubTemplate:
        def render(self, **kwargs):
            captured.update(kwargs)
            return "<html></html>"

    def _fake_get_template(self, name):
        return _StubTemplate()

    monkeypatch.setattr(jinja2.Environment, "get_template", _fake_get_template)

    spec = {
        "name": "s1",
        "findings": [{"kind": "theoretical"}, {"kind": "theoretical"}],
    }
    render_study_detail_html(tmp_path, "s1", spec)

    assert captured["study"]["kind"] == "theoretical"


def test_render_study_detail_html_preserves_explicit_kind(monkeypatch, tmp_path):
    from vivarium_workbench.lib.study_page import render_study_detail_html

    captured = {}

    class _StubTemplate:
        def render(self, **kwargs):
            captured.update(kwargs)
            return "<html></html>"

    def _fake_get_template(self, name):
        return _StubTemplate()

    monkeypatch.setattr(jinja2.Environment, "get_template", _fake_get_template)

    spec = {"name": "s2", "kind": "biological"}
    render_study_detail_html(tmp_path, "s2", spec)

    assert captured["study"]["kind"] == "biological"

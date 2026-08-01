"""Wiring test for study `kind` reaching the study-detail template context,
plus (Task 4) real served-HTML assertions for the restructured header.

The `data-study-kind=` HTML attribute itself is added by study-detail.html in
a later task (Task 4), so there is no markup to assert on yet. Instead this
captures the kwargs `render_study_detail_html` passes to Jinja2's
``Template.render()`` (i.e. what the template sees as ``study.kind``) by
stubbing out template rendering — proving the wiring without depending on
markup that doesn't exist yet.
"""
from __future__ import annotations

import jinja2
import yaml
import pytest


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


# ---------------------------------------------------------------------------
# Task 4: header restructure (7 elements -> 3) — real served-HTML assertions.
# ---------------------------------------------------------------------------

def test_header_has_kind_tag_and_question_and_no_spine(tmp_path, dashboard_client):
    """End-to-end: GET /studies/<slug> must emit the kind tag + promoted
    question headline, and must NOT emit the retired #spine-summary table.

    This is the flip of Task 1's context-only wiring test above (which
    stubbed out Jinja2 rendering because the template tag didn't exist yet)
    into a plain assertion against real served markup, now that Task 4 has
    added the `data-study-kind=` tag to study-detail.html.
    """
    ws = tmp_path / "ws"
    sd = ws / "studies" / "kind-question-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "kind-question-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/kind-question-study")
    assert resp.status_code == 200
    html = resp.text

    assert 'data-study-kind=' in html
    assert 'data-study-kind="biological"' in html
    assert 'id="study-question-headline"' in html
    assert "Does the demo composite run correctly?" in html
    assert 'id="spine-summary"' not in html


# ---------------------------------------------------------------------------
# Task 5: readiness -> inline link; #spine-summary populator removed.
# ---------------------------------------------------------------------------

def test_readiness_is_inline_not_banner(tmp_path, dashboard_client):
    """The readiness mount is still server-rendered as an empty container
    (its content is filled client-side by _renderReadinessPanel after
    GET /api/report-lint, so the "⚠ N gaps" / "✓ ready" text itself is NOT
    visible in served HTML and must not be asserted here). Only assert the
    server-side facts: the `#readiness-panel` mount exists and no trace of
    the retired `#spine-summary` banner/table remains.
    """
    ws = tmp_path / "ws"
    sd = ws / "studies" / "readiness-inline-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "readiness-inline-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/readiness-inline-study")
    assert resp.status_code == 200
    html = resp.text

    assert 'id="readiness-panel"' in html
    assert 'id="spine-summary"' not in html
    assert 'spine-summary' not in html
    assert 'spine-row' not in html


# ---------------------------------------------------------------------------
# Task 6: overview de-biology — delete biology section, fold authored
# biological_summary into a fourth "Summary" card in Question & Approach,
# drop the counts strip.
# ---------------------------------------------------------------------------

def test_overview_no_biology_lean(tmp_path, dashboard_client):
    """The standalone biology block (heading + derived-from-findings
    restatement) and the counts strip must both be gone."""
    ws = tmp_path / "ws"
    sd = ws / "studies" / "no-biology-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "no-biology-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "findings": [{"statement": "Something was found."}],
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/no-biology-study")
    assert resp.status_code == 200
    html = resp.text

    assert "Biology — what this study is about" not in html
    assert "Derived from findings" not in html
    assert "study-counts-strip" not in html


def test_overview_biological_summary_folds_into_qa_card(tmp_path, dashboard_client):
    """An authored `biological_summary` renders as a fourth card inside the
    Question & Approach section (same `purpose-callout` class family as the
    Question/Hypothesis/Mechanism cards), not as a standalone "Biology"
    section/heading."""
    ws = tmp_path / "ws"
    sd = ws / "studies" / "qa-summary-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "qa-summary-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {
            "question": "Does the demo composite run correctly?",
            "expected_outcome": "Yes, it runs without error.",
            "mechanism": "Swap the metabolism process for a reduced model.",
        },
        "biological_summary": "Plain-English mechanism narrative for a non-modeler.",
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/qa-summary-study")
    assert resp.status_code == 200
    html = resp.text

    assert "Biology — what this study is about" not in html
    assert "Derived from findings" not in html
    assert "study-counts-strip" not in html

    # The Summary card appears, styled as a `purpose-callout` (same class as
    # the Question/Hypothesis/Mechanism cards it sits alongside).
    assert "Plain-English mechanism narrative for a non-modeler." in html
    summary_idx = html.index("Plain-English mechanism narrative for a non-modeler.")
    card_start = html.rindex('<div class="purpose-callout"', 0, summary_idx)
    assert card_start != -1
    assert "<strong>Summary.</strong>" in html[card_start:summary_idx + 40]

    # It lives near the Question card, inside the Question & Approach
    # section — not under its own "Biology" heading.
    question_idx = html.index("Question &amp; approach")
    assert question_idx < card_start


def test_overview_biological_summary_renders_for_legacy_schema_too(tmp_path, dashboard_client):
    """Fix round 1: a legacy-schema study (no `purpose` block, so the
    `{% else %}` branch renders) with an authored `biological_summary` must
    still get the Summary card — it must not silently drop the text just
    because the study predates the v4 `purpose.*` schema."""
    ws = tmp_path / "ws"
    sd = ws / "studies" / "legacy-summary-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "legacy-summary-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "question": "Legacy-schema research question.",
        "biological_summary": "Legacy-schema plain-English mechanism narrative.",
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/legacy-summary-study")
    assert resp.status_code == 200
    html = resp.text

    assert "Biology — what this study is about" not in html
    assert "Derived from findings" not in html
    assert "study-counts-strip" not in html

    assert "Legacy-schema plain-English mechanism narrative." in html
    assert "<strong>Summary.</strong>" in html


# ---------------------------------------------------------------------------
# Task 7: Decide tab — "Biological validation" -> "Empirical validation"
# rename (data-* attrs stay `biological_validation` for back-compat), and
# strip the two explanatory paragraphs (VERDICT & CONCLUSION intro, and the
# three-track "Each track is independent..." explainer). Fix round 1: also
# covers the "Conclusion logic — gate decision" block's <em>Biological
# validation:</em> label (rendered only when
# conclusion_logic.if_primary_tests_pass.biological_validation is set), which
# round 1 of this task missed.
# ---------------------------------------------------------------------------

def test_decide_empirical_rename_and_no_prose(tmp_path, dashboard_client):
    ws = tmp_path / "ws"
    sd = ws / "studies" / "decide-empirical-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "decide-empirical-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
        # Populate the conclusion-logic gate-decision branch so the
        # <em>Empirical validation:</em> label (formerly "Biological
        # validation:") actually renders in served HTML, not just the
        # three-track verdict card's labels.
        "conclusion_logic": {
            "if_primary_tests_pass": {
                "biological_validation": "Matches the literature band.",
            },
        },
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/decide-empirical-study")
    assert resp.status_code == 200
    html = resp.text

    assert "Empirical validation" in html
    assert "Biological validation" not in html
    assert "Synthesises the latest run" not in html
    assert "Each track is independent" not in html

    # The conclusion-logic gate-decision line rendered (proves the assertion
    # above actually covers that block, not just the three-track card).
    assert "Matches the literature band." in html

    # Back-compat: the machine-readable attributes/dict keys must be
    # unchanged — only the human-readable label text was renamed.
    assert 'data-verdict-track="biological_validation"' in html
    assert 'data-narrative-path="conclusion_verdicts.biological_validation.basis"' in html


# ---------------------------------------------------------------------------
# Task 8: Simulations tab -> read-only runs table. Remove the Reproduce/CLI
# card, both explanatory paragraphs, the simulation_set / "Simulation set (N
# runs planned)" cards block, the Configure & Run mount, and the remote-run
# (smsvpctest) form. Keep only the #study-sim-table mount (populated
# client-side from /api/simulations, so row data itself isn't in served
# HTML — assert only the mount + absence of the removed controls).
# ---------------------------------------------------------------------------

def test_simulations_is_readonly_table(tmp_path, dashboard_client):
    ws = tmp_path / "ws"
    sd = ws / "studies" / "sims-readonly-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "sims-readonly-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
        # Legacy simulation_set entry — must NOT render as cards anymore.
        "simulation_set": [{
            "name": "core-sim",
            "kind": "single",
            "base_model": "pkg.composites.core",
            "status": "ready",
            "seeds": [0],
            "duration_min": 5,
        }],
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/sims-readonly-study")
    assert resp.status_code == 200
    html = resp.text

    assert 'id="reproduce-card"' not in html
    assert 'Run on remote' not in html
    assert 'Simulation set' not in html
    assert 'study-configure-run' not in html


def test_visualizations_stripped_to_gallery(tmp_path, dashboard_client):
    """Task 9: Visualizations tab is one figure gallery — no explanatory
    prose and no per-mount section chrome (headings), just the three mounts
    (native gallery, embedded-viz iframes, latest-run charts) under a single
    `study-figures` wrapper + `<h2>Figures</h2>`."""
    ws = tmp_path / "ws"
    sd = ws / "studies" / "viz-gallery-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "viz-gallery-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/viz-gallery-study")
    assert resp.status_code == 200
    html = resp.text

    assert 'id="panel-visualize"' in html
    assert 'study-figures' in html
    assert 'id="native-gallery-panel"' in html
    assert 'id="viz-charts-panel"' in html

    assert 'Figures for this study' not in html
    assert 'native-gallery-section' not in html
    assert 'Baseline analysis gallery' not in html
    assert 'Embedded visualizations' not in html
    assert 'Latest-run charts' not in html
    assert 'No baseline figures yet' not in html
    assert 'id="study-sim-table"' in html

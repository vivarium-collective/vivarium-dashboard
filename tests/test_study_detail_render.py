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
    assert 'id="study-sim-table"' in html


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


# ---------------------------------------------------------------------------
# Task 10: Tests — merge Report Cards + Behavioral Tests into ONE concept.
# The Tests pillar now has a single sub-nav member; report cards + behavioral
# gates render top-to-bottom in one `data-kind="tests"` panel, led by a
# gate/audit summary strip. No separate "Report Cards" tab/pillar remains.
# ---------------------------------------------------------------------------

def test_tests_merged_single_concept(tmp_path, dashboard_client):
    ws = tmp_path / "ws"
    sd = ws / "studies" / "tests-merged-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "tests-merged-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/tests-merged-study")
    assert resp.status_code == 200
    html = resp.text

    # Gate/audit summary strip mount is present.
    assert 'tests-gate-summary' in html
    # The old explanatory prose is gone.
    assert 'Graded comparison scorecards' not in html
    # The report-cards sub-nav member / pillar-tab / standalone panel are gone.
    assert 'data-kind="report-cards"' not in html
    assert 'id="panel-report-cards"' not in html
    assert '_setStudyTab(\'report-cards\')' not in html
    # The report-cards mount now lives INSIDE the tests panel (one concept).
    tests_panel = html[html.index('id="panel-tests"'):html.index('id="panel-conclusions"')]
    assert 'id="report-cards-panel"' in tests_panel
    assert '<h2>Tests</h2>' in tests_panel
    assert 'Audit —' in tests_panel


# ---------------------------------------------------------------------------
# Task 11: Exports — strip explanatory prose. Keeps its function (result-files
# list, "Download all (.zip)" link, raw simulation-data list) but loses the
# tutorial-style paragraphs; gets a plain `<h2>Exports</h2>` heading.
# ---------------------------------------------------------------------------

def test_exports_functional_no_prose(tmp_path, dashboard_client):
    ws = tmp_path / "ws"
    sd = ws / "studies" / "exports-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "exports-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/exports-study")
    assert resp.status_code == 200
    html = resp.text

    # Functional bits kept.
    assert 'id="data-files"' in html
    assert 'id="raw-data-list"' in html
    assert 'id="data-download-all"' in html
    assert '/api/study-analysis-zip?study=exports-study' in html

    # Plain heading kept, in the right panel.
    data_panel = html[html.index('id="panel-data"'):html.index('id="panel-tests"')]
    assert '<h2>Exports</h2>' in data_panel

    # Explanatory/tutorial prose is gone.
    assert 'Tabular outputs' not in html
    assert 'Click a file to' not in html
    assert "Each run's raw emitter store" not in html
    assert 'Analysis outputs above are derived' not in html


# ---------------------------------------------------------------------------
# Fable Increment A, Task 1: model_change.modified_processes must render as
# formatted fields, never as a bare Python dict repr (R1 — never render a
# raw Python dict or JSON blob in the default view).
# ---------------------------------------------------------------------------

def test_modified_processes_renders_fields_not_dict_repr(tmp_path, dashboard_client):
    ws = tmp_path / "ws"
    sd = ws / "studies" / "modified-processes-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "modified-processes-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
        "model_change": {
            "base_model": "pkg.composites.core",
            "modified_processes": [
                {
                    "name": "EcoliWCM._handle_division",
                    "why": "Daughter cells were not rehydrating water mass on split.\nFixed by recomputing hydration post-division.",
                    "status": "required",
                    "requirement_id": "req-2-daughter-hydration-fix",
                },
                "a legacy plain-string entry",
            ],
        },
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/modified-processes-study")
    assert resp.status_code == 200
    html = resp.text

    # Never a raw Python dict repr.
    assert "{'name':" not in html
    assert "'requirement_id':" not in html
    assert "{&#39;name&#39;" not in html

    # Fields rendered individually.
    assert "<code>EcoliWCM._handle_division</code>" in html
    assert "Daughter cells were not rehydrating water mass on split." in html
    assert "required" in html
    assert "req-2-daughter-hydration-fix" in html

    # Plain-string entries (the `is mapping` guard's else branch) still render.
    assert "a legacy plain-string entry" in html


# ---------------------------------------------------------------------------
# Fable Increment A, Task 8: delete three redundant/vestigial Overview blocks
# (§4.1 "Cut" — pure deletions only; the Relocate items — pipeline_gate /
# assumptions / limitations moving to Decide — are a later increment and are
# untouched here):
#   1. the Status subsection (verbatim duplicate of the header status pill)
#   2. the behavioral-tests count strip + "View on Tests tab ->"
#   3. the follow-up studies pointer block ("canonical surface is Decide")
# Findings / Question&approach / Conclusion must keep rendering.
# ---------------------------------------------------------------------------

def test_overview_deleted_blocks_absent_core_content_kept(tmp_path, dashboard_client):
    ws = tmp_path / "ws"
    sd = ws / "studies" / "overview-declutter-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "overview-declutter-study",
        "kind": "biological",
        "phase": "simulate",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
        # Would render the tests-count strip + "View on Tests tab" if the
        # block still existed.
        "behavior_tests": [{"name": "beh-a", "classification": "primary"}],
        # Would render the follow-ups pointer block if it still existed.
        "follow_up_studies": [{"id": "study-2", "question": "Next question?"}],
        "findings": [{"statement": "Daughter cells hydrate within one tick."}],
        "report": {"conclusion": "The model reproduces the expected behavior."},
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/overview-declutter-study")
    assert resp.status_code == 200
    html = resp.text

    overview = html[html.index('id="panel-overview"'):html.index('id="panel-compose"')]

    # 1. Status subsection (verbatim header-pill duplicate) is gone.
    assert '<h3 class="overview-label">Status</h3>' not in overview
    assert 'Lifecycle phase:' not in overview

    # 2. Behavioral-tests count strip + its Tests-tab link is gone.
    assert '<h2 class="overview-label">Behavioral tests</h2>' not in overview
    assert 'View on Tests tab' not in overview

    # 3. Follow-up studies pointer block is gone.
    assert '<h2 class="overview-label">Follow-up studies</h2>' not in overview
    assert 'View follow-ups on the' not in overview
    assert 'canonical surface is the' not in overview

    # Findings / Question & approach / Conclusion still render on Overview.
    assert 'Question &amp; approach' in overview
    assert 'Findings' in overview
    assert 'Daughter cells hydrate within one tick.' in overview
    assert '<h2 class="overview-label">Conclusion</h2>' in overview
    assert 'The model reproduces the expected behavior.' in overview

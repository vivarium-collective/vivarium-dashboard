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

from pathlib import Path

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


def test_visualizations_empty_state_unions_all_three_sources(tmp_path, dashboard_client):
    """Fable A #3: the "No figures yet." empty state must not be baked into
    the served HTML as visible text next to real figures. It lives in a
    single shared #figures-empty-message element, hidden by default, that JS
    only reveals once the native gallery AND latest-run charts (both loaded
    async) AND the embed_visualizations iframes (server-rendered here) have
    all reported empty. A study WITH embed_visualizations must still
    server-render the embed markup, so the union has content even though the
    (async, JS-only) native gallery can't be observed from served HTML."""
    ws = tmp_path / "ws"
    sd = ws / "studies" / "viz-gallery-study-embeds"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "viz-gallery-study-embeds",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
        "embed_visualizations": [
            {"name": "Preview", "url": "/reports/figures/viz-gallery-study-embeds/preview.html"},
        ],
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/viz-gallery-study-embeds")
    assert resp.status_code == 200
    html = resp.text

    # The embed renders as real figure content in the union.
    assert 'embed-viz-card' in html
    assert 'Preview' in html

    # The empty-state text exists exactly once, as the shared element, and
    # starts hidden — it is not painted unconditionally by any one source.
    assert html.count('No figures yet.') == 1
    assert 'id="figures-empty-message"' in html
    empty_idx = html.index('id="figures-empty-message"')
    tag_start = html.rindex('<p', 0, empty_idx)
    tag_end = html.index('>', empty_idx)
    assert 'style="display:none"' in html[tag_start:tag_end]


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
# Fable Increment A, Task 5 (change #4): Tests tab used to render its gate
# set twice — a client-side "N/M gates passed" strip that ALSO built its own
# per-gate ✓/✗ `<li>` rows (_renderTestsGateSummary), stacked directly above
# the server-rendered "Behavioral tests" list (#tests-list) that lists the
# same gates again, richer (requires/Assertion). Fable §4.6: merge into one
# score line + one list. The gate-summary mount (#tests-gate-summary) stays
# as the score-line container, but its render function must no longer build
# a second per-gate list — that detail lives ONCE, in #tests-list.
# ---------------------------------------------------------------------------

def test_tests_gate_summary_not_duplicated_by_behavioral_list(tmp_path, dashboard_client):
    import re
    from pathlib import Path
    import vivarium_workbench

    ws = tmp_path / "ws"
    sd = ws / "studies" / "gate-dedup-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "gate-dedup-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
        "behavior_tests": [
            {"name": "daughters_hydrated", "classification": "primary",
             "measure": "daughter_mass_ratio", "pass_if": "ratio <= 2.0"},
            {"name": "two_generations_complete", "classification": "primary",
             "requires_simulation": "baseline_2gen"},
        ],
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/gate-dedup-study")
    assert resp.status_code == 200
    html = resp.text

    tests_panel = html[html.index('id="panel-tests"'):html.index('id="panel-conclusions"')]

    # Exactly one score-line mount and one per-gate detail list in the
    # server-rendered markup — no second copy of either.
    assert tests_panel.count('id="tests-gate-summary"') == 1
    assert tests_panel.count('id="tests-list"') == 1

    # Each declared gate gets exactly one row (id="bt-<name>") in the served
    # panel — in the behavioral list; nothing pre-renders a second row for
    # it into the gate-summary strip server-side.
    assert tests_panel.count('id="bt-daughters_hydrated"') == 1
    assert tests_panel.count('id="bt-two_generations_complete"') == 1

    # The client-side gate-summary renderer (_renderTestsGateSummary) must
    # build the score line only, not a second per-gate list — assert its
    # function body no longer iterates the gate/test set to emit rows (the
    # duplication this task removes) while still emitting the score line.
    js = (Path(vivarium_workbench.__file__).parent / "static" / "study-detail.js").read_text(
        encoding="utf-8"
    )
    m = re.search(
        r"function _renderTestsGateSummary\(spec\) \{(.*?)\n  \}",
        js,
        re.DOTALL,
    )
    assert m, "_renderTestsGateSummary not found in study-detail.js"
    fn_body = m.group(1)
    assert "gates passed" in fn_body
    # No per-gate row construction left in the summary renderer (the old
    # duplicate list): no per-test iteration building <li> rows.
    assert "tests.map(" not in fn_body
    assert "<li" not in fn_body


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


# ---------------------------------------------------------------------------
# Fable A #6: delete #study-subnav + the pillar/member indirection — the top
# `.study-pillar` buttons drive tab switching directly.
# ---------------------------------------------------------------------------

def test_pillars_drive_tabs_directly_no_subnav(tmp_path, dashboard_client):
    """Real served-HTML assertion (not just static grep): the second tab
    row (#study-subnav) must be entirely absent, all 8 `.study-pillar`
    buttons must be present and wired to call `_setStudyTab(<kind>)`
    directly, and the deleted pillar/member-indirection JS functions must
    not appear anywhere in the served page or its JS asset.
    """
    ws = tmp_path / "ws"
    sd = ws / "studies" / "pillars-direct-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "pillars-direct-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/pillars-direct-study")
    assert resp.status_code == 200
    html = resp.text

    # Second tab row is gone.
    assert 'id="study-subnav"' not in html
    assert 'study-subnav' not in html

    # All 8 pillar buttons present, each carrying data-kind and calling
    # _setStudyTab(kind) directly (pillar name == kind, except
    # "decide" -> "conclusions").
    pillar_to_kind = {
        "understand": "overview", "compose": "compose", "simulate": "simulate",
        "readouts": "readouts", "visualize": "visualize", "tests": "tests",
        "decide": "conclusions", "data": "data",
    }
    for pillar, kind in pillar_to_kind.items():
        assert f'data-kind="{kind}"' in html and f"_setStudyTab('{kind}')" in html, \
            f"pillar {pillar!r} not wired to _setStudyTab('{kind}')"
    import re
    assert len(re.findall(r'<button class="study-pillar[^"]*"', html)) == 8

    # No pillar/member indirection left anywhere (grep-proven, both served
    # HTML and the JS asset it references).
    for fn in ("_setStudyPillar", "_showPillarSubnav", "_pillarForKind"):
        assert fn not in html
    js_path = Path(__file__).resolve().parents[1] / "vivarium_workbench" / "static" / "study-detail.js"
    js = js_path.read_text()
    for fn in ("_setStudyPillar", "_showPillarSubnav", "_pillarForKind"):
        assert fn not in js, f"{fn} should have been deleted from study-detail.js"


# ---------------------------------------------------------------------------
# Fable G1: act rail (five acts + per-act gate dots) + reposition Readouts to
# slot 3, so the acts group contiguously (Design = Model+Readouts, Evidence =
# Simulations+Visualizations). Spec: 2026-08-01-study-design-fable-pass.md
# §9.2 (five acts), §9.3 (revised tab bar + act rail).
# ---------------------------------------------------------------------------

def test_act_rail_renders_above_tab_nav(tmp_path, dashboard_client):
    """The five act labels render above `.study-pillars`, each with a
    gate-dot element carrying a stable `data-gate` hook (state wiring is
    Task G2's job — here it must be present but neutral/not-assessed)."""
    ws = tmp_path / "ws"
    sd = ws / "studies" / "act-rail-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "act-rail-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/act-rail-study")
    assert resp.status_code == 200
    html = resp.text

    # Act rail sits above the tab nav (before .study-pillars in document order).
    rail_i = html.index('class="act-rail"')
    pillars_i = html.index('class="study-pillars"')
    assert rail_i < pillars_i, "act rail must render above the tab buttons"

    # Five act labels, in order, plus the Record-drawer label set apart.
    for label in ("The Study", "Design", "Evidence", "Assurance", "Decision", "Exports"):
        assert label in html[rail_i:pillars_i], f"act label {label!r} missing from act rail"
    order = [html.index(label, rail_i) for label in
             ("The Study", "Design", "Evidence", "Assurance", "Decision", "Exports")]
    assert order == sorted(order), "act labels out of order"

    # Each of the five acts (not Exports) carries a gate-dot hook: a stable
    # class + data-gate attribute, neutral state — G2 recolors it, doesn't
    # need to touch this markup.
    import re
    dots = re.findall(r'<span class="act-gate-dot" data-gate="([a-z]+)"[^>]*>', html)
    assert dots == ["study", "design", "evidence", "assurance", "decision"], dots
    assert 'data-gate-state="not-assessed"' in html


def test_readouts_repositioned_to_slot_three(tmp_path, dashboard_client):
    """Tab order is now Overview, Model, Readouts, Simulations,
    Visualizations, Tests, Decide, Exports — Readouts moves so Design
    (Model+Readouts) and Evidence (Simulations+Visualizations) each group
    contiguously per act. Panel switching is unaffected (`_setStudyTab`
    selects by `data-kind`, not position)."""
    ws = tmp_path / "ws"
    sd = ws / "studies" / "readouts-order-study"
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": "readouts-order-study",
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
        "status": "in_progress",
    }))

    client = dashboard_client(ws)
    resp = client.get("/studies/readouts-order-study")
    assert resp.status_code == 200
    html = resp.text

    kinds_in_order = [
        "overview", "compose", "readouts", "simulate", "visualize",
        "tests", "conclusions", "data",
    ]
    positions = [html.index(f'data-kind="{k}"') for k in kinds_in_order]
    assert positions == sorted(positions), (
        f"expected pillar order {kinds_in_order}, got positions {positions}"
    )
    # Readouts now precedes Simulations in the pillar row.
    assert html.index('data-kind="readouts"') < html.index('data-kind="simulate"')

    # All 8 pillars still present and wired to _setStudyTab.
    for kind in kinds_in_order:
        assert f'data-kind="{kind}"' in html and f"_setStudyTab('{kind}')" in html


# ---------------------------------------------------------------------------
# Fable G2: six status axes → six gates in `status ▾`, computed-vs-authored,
# and feeding the act-rail gate dots (G1). Spec: 2026-08-01-study-design-
# fable-pass.md §13 (gating model), §13.1 (where gates live), §13.2 (states).
# ---------------------------------------------------------------------------

def _write_g2_study(ws, slug, extra_spec):
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    spec = {
        "schema_version": 3,
        "name": slug,
        "kind": "biological",
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
        "purpose": {"question": "Does the demo composite run correctly?"},
    }
    spec.update(extra_spec)
    (sd / "study.yaml").write_text(yaml.safe_dump(spec))


def test_status_ladder_shows_six_gate_names(tmp_path, dashboard_client):
    """`status ▾` relabels the six axes as the six gates (§13's table):
    Plan / Execution / Evidence / Quality / Decision / Release — not the old
    axis words (Design/Implementation/Simulation/Evaluation/Gate/Expert
    review)."""
    ws = tmp_path / "ws"
    _write_g2_study(ws, "gate-names-study", {"design_status": "designed"})
    client = dashboard_client(ws)
    resp = client.get("/studies/gate-names-study")
    assert resp.status_code == 200
    html = resp.text

    panel_i = html.index('class="status-detail-panel"')
    panel_end = html.index("</details>", panel_i)
    seg = html[panel_i:panel_end]
    for gate_name in ("Plan", "Execution", "Evidence", "Quality", "Decision", "Release"):
        assert gate_name in seg, f"gate name {gate_name!r} missing from status ladder"


def test_status_ladder_shows_authored_axis_state(tmp_path, dashboard_client):
    """A study with an authored axis (design_status) shows that gate's
    (Plan's) authored value in the ladder."""
    ws = tmp_path / "ws"
    _write_g2_study(ws, "authored-axis-study", {"design_status": "designed"})
    client = dashboard_client(ws)
    resp = client.get("/studies/authored-axis-study")
    assert resp.status_code == 200
    html = resp.text

    panel_i = html.index('class="status-detail-panel"')
    panel_end = html.index("</details>", panel_i)
    seg = html[panel_i:panel_end]
    assert "1 · Plan" in seg
    assert "designed" in seg
    assert 'gate-state-passed' in seg


def test_status_ladder_shows_computed_vs_authored_indicator(tmp_path, dashboard_client):
    """Where a computed value exists for a gate (Execution/Evidence, sourced
    from viva_superpowers.study_status.derive_status, already attached to the
    spec as `derived_status` by load_study_detail_spec) a `◆ computed:`
    indicator renders in the gate ladder body."""
    ws = tmp_path / "ws"
    _write_g2_study(ws, "computed-axis-study", {
        "behavior_tests": [{"name": "t1"}],
        "runs": [{"name": "r1", "status": "completed",
                   "outcomes": {"t1": {"result": "PASS"}}}],
    })
    client = dashboard_client(ws)
    resp = client.get("/studies/computed-axis-study")
    assert resp.status_code == 200
    html = resp.text

    panel_i = html.index('class="status-detail-panel"')
    panel_end = html.index("</details>", panel_i)
    seg = html[panel_i:panel_end]
    assert "gate-computed-chip" in seg
    assert "◆ computed:" in seg
    # Execution's computed value is sourced from run history (derived_status).
    assert "2 · Execution" in seg


def test_act_rail_dots_reflect_gate_states(tmp_path, dashboard_client):
    """A study with real gate data does NOT render every act dot as
    not-assessed — G2 feeds `data-gate-state` from the computed gate ladder
    (G1 shipped the hooks neutral; this is the wiring)."""
    import re

    ws = tmp_path / "ws"
    _write_g2_study(ws, "act-dots-study", {
        "design_status": "designed",
        "gate_status": "passed",
        "behavior_tests": [{"name": "t1"}],
        "runs": [{"name": "r1", "status": "completed",
                   "outcomes": {"t1": {"result": "FAIL"}}}],
    })
    client = dashboard_client(ws)
    resp = client.get("/studies/act-dots-study")
    assert resp.status_code == 200
    html = resp.text

    dots = re.findall(
        r'<span class="act-gate-dot" data-gate="([a-z]+)" data-gate-state="([a-z-]+)">',
        html,
    )
    assert len(dots) == 5, dots
    states = {gate: state for gate, state in dots}
    # design_status: designed -> Plan passes -> the "design" act dot is "passed".
    assert states["design"] == "passed"
    # Not every dot is the G1 placeholder "not-assessed" for a study with data.
    assert set(states.values()) != {"not-assessed"}

# tests/test_compose_unification.py
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "vivarium_workbench/templates/study-detail.html").read_text()


def test_panel_compose_exists_and_old_wrappers_gone():
    assert 'data-kind="compose" id="panel-compose"' in HTML
    for old in ['id="panel-build"', 'id="panel-baseline"', 'id="panel-variants"', 'id="panel-interventions"']:
        assert old not in HTML, f"old wrapper still present: {old}"


def test_single_compose_member_button():
    import re
    compose_btns = re.findall(r'<button class="study-tab"[^>]*data-pillar="compose"[^>]*>', HTML)
    assert len(compose_btns) == 1, f"expected 1 compose member button, got {len(compose_btns)}"
    assert 'data-kind="compose" data-pillar="compose"' in HTML
    for old in ["_setStudyTab('build')", "_setStudyTab('baseline')", "_setStudyTab('variants')", "_setStudyTab('interventions')"]:
        assert old not in HTML, f"old compose tab button call still present: {old}"


def _panel_compose():
    i = HTML.index('id="panel-compose"')
    nxt = HTML.find('class="study-tab-panel"', i + 10)
    return HTML[i: nxt if nxt != -1 else len(HTML)]


def test_inner_hooks_preserved_in_compose():
    p = _panel_compose()
    # The legacy v2 baseline/variants/interventions CRUD was retired; the Model
    # (compose) panel now surfaces the composite + its resolved config + the v3
    # conditions editor.
    assert "data-model-composite" in p and "model-config-mount" in p  # composite + resolved config
    assert "_openCompositeLoom" in p                                  # open in the Composite Explorer
    assert "cond-block" in p                                          # v3 conditions editor
    # Build block guard still present inside the merged panel.
    assert "study.model_change or study.implementation_requirements" in p


def test_other_panels_untouched():
    # Post pillar-unification (Simulate/Visualize merge), the non-compose panels
    # are overview / simulate / visualize / tests / conclusions; the old split
    # simulations/observables/runs/visualizations panels were merged away.
    for k in ["overview", "simulate", "visualize", "tests", "conclusions"]:
        assert f'id="panel-{k}"' in HTML, f"unrelated panel disturbed: panel-{k}"


def test_subnav_hidden_for_single_member_pillar():
    js = (ROOT / "vivarium_workbench/static/study-detail.js").read_text()
    # _showPillarSubnav hides the sub-nav row when the pillar has <= 1 member
    i = js.index("function _showPillarSubnav")
    block = js[i:i + 700]
    assert "study-subnav" in block
    # a count of the pillar's members + a conditional hide of the container
    assert ("<= 1" in block) or ("< 2" in block) or ("=== 1" in block) or (".length" in block and "display" in block)


def test_build_guard_preserves_conditions_and_baseline():
    # Regression: the merged build-block guard must mirror the pre-merge
    # panel-build guard so a non-v3 study with conditions/baseline (but no
    # model_change/impl_reqs) keeps its Model + Conditions sections.
    p = _panel_compose()
    i = p.index("_has_build =")
    guard = p[i:i + 120]
    for field in ["study.model_change", "study.implementation_requirements", "study.conditions", "study.baseline"]:
        assert field in guard, f"build guard dropped {field}: {guard!r}"


def test_analyses_section_present_and_reachable_on_the_study_page():
    # Regression: an earlier "Analyses" authoring control was wired only into
    # the legacy Investigation-detail panel (#investigation-detail inside
    # #page-studies), which no current navigation path opens — dead UI. This
    # one lives on the Model (compose) tab of the Study page, which every
    # study (grouped or ungrouped) is actually reachable through.
    p = _panel_compose()
    assert 'id="study-analyses-list"' in p
    assert 'onclick="_saveStudyAnalyses()"' in p
    assert 'id="study-analyses-status"' in p
    # Rendered unconditionally within the panel (outside the _has_build guard)
    # so a brand-new blank study can still have its analyses configured.
    assert "endif %}\n\n  {# Analyses" in HTML or "{# Analyses" in HTML


def test_save_study_analyses_posts_to_the_working_endpoint():
    js = (ROOT / "vivarium_workbench/static/study-detail.js").read_text()
    i = js.index("function _saveStudyAnalyses")
    block = js[i:i + 800]
    assert "/api/study-set-analyses" in block
    assert "studyName()" in block
    assert "window._saveStudyAnalyses = _saveStudyAnalyses" in js


def test_baseline_composite_replace_control_present_and_wired():
    # Regression: the pre-unification "+ Add baseline" form (_submitBaselineAdd)
    # was removed from this template, leaving its JS handler and the
    # /api/study-baseline-add /-remove endpoints orphaned — no UI path could
    # ever set/replace a study's composite ref once created (e.g. to fix the
    # "+ Study" blank scaffold's placeholder ref). This control reuses those
    # existing, working endpoints instead of adding a new one.
    p = _panel_compose()
    assert 'class="baseline-composite-input"' in p
    assert 'class="action-btn baseline-composite-set"' in p
    assert "baseline-composite-status" in p
    js = (ROOT / "vivarium_workbench/static/study-detail.js").read_text()
    i = js.index("baseline-composite-set", js.index("bindAll"))
    block = js[i:i + 900]
    assert "/api/study-baseline-remove" in block
    assert "/api/study-baseline-add" in block

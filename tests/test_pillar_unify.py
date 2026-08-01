from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "vivarium_workbench/templates/study-detail.html").read_text()
JS = (ROOT / "vivarium_workbench/static/study-detail.js").read_text()


def test_merged_panels_exist_and_old_gone():
    assert 'id="panel-simulate"' in HTML and 'data-kind="simulate"' in HTML
    assert 'id="panel-visualize"' in HTML and 'data-kind="visualize"' in HTML
    for old in ['id="panel-simulations"', 'id="panel-runs"', 'id="panel-observables"', 'id="panel-visualizations"']:
        assert old not in HTML, f"old wrapper still present: {old}"


def test_single_member_buttons():
    # Post pillar/member-indirection removal (Fable A #6): there is exactly
    # one `.study-pillar` button per kind — no subnav member buttons left.
    import re
    for p in ("simulate", "visualize"):
        btns = re.findall(r'<button class="study-pillar"[^>]*data-kind="%s"[^>]*>' % p, HTML)
        assert len(btns) == 1, f"{p}: expected 1 pillar button, got {len(btns)}"
    for old in ["_setStudyTab('simulations')", "_setStudyTab('observables')"]:
        assert old not in HTML


def _panel(idattr):
    i = HTML.index(idattr)
    nxt = HTML.find('class="study-tab-panel"', i + 10)
    return HTML[i: nxt if nxt != -1 else len(HTML)]


def test_inner_hooks_preserved():
    # Readouts split out to their own tab; charts stay on Visualizations.
    readouts = _panel('id="panel-readouts"')
    assert 'readouts-table' in readouts
    viz = _panel('id="panel-visualize"')
    assert 'viz-charts-panel' in viz
    sim = _panel('id="panel-simulate"')
    assert 'panel-runs' not in HTML  # wrapper gone; runs render via the Sim-DB table:
    assert 'study-sim-table' in sim


def test_other_panels_untouched():
    for k in ["overview", "compose", "tests", "conclusions"]:
        assert f'id="panel-{k}"' in HTML


def test_readouts_and_visualize_load_their_own_content():
    # Readouts tab loads the readouts table; Visualizations loads the charts.
    i = JS.index("function _setStudyTab")
    block = JS[i:i + 800]
    assert "kind === 'readouts'" in block and "_loadReadouts()" in block
    assert "kind === 'visualize'" in block and "_loadCharts('viz-charts-panel')" in block
    # old single-kind loaders gone
    assert "kind === 'visualizations'" not in JS
    assert "kind === 'observables'" not in JS


def test_callers_repointed():
    assert "_setStudyTab('runs')" not in JS
    assert "_setStudyTab('visualizations')" not in JS


# ---------------------------------------------------------------------------
# Task V2 (Fable §4.5): the native gallery + inline charts sources render the
# same `.figure-card` shell (template already gives the embed source that
# class), with a caption row (muted source chip, title, and a run-link
# rendered conditionally on run_id). Card markup is built client-side, so
# these assert against the JS source rather than served HTML.

def test_native_gallery_card_uses_figure_card_and_conditional_run_link():
    i = JS.index("function _loadNativeGallery")
    block = JS[i:i + 2400]
    assert '"figure-card"' in block
    assert 'font-weight:600;font-size:0.92em' not in block  # old bold native label gone
    assert 'figure-caption-row' in block and 'figure-source-chip' in block
    assert 'figure-run-link' in block and 'data-run-id' in block
    # build_study_native_gallery returns one run_id for the whole gallery;
    # the caption is built conditionally so a study with no completed run
    # (run_id is None) omits the link instead of fabricating one.
    assert 'runId\n' in block or 'var runCaption = runId' in block
    assert '_wireFigureRunLinks(host)' in block


def test_chart_card_uses_figure_card_not_chart_card_box():
    i = JS.index("function _renderChartCard")
    block = JS[i:i + 900]
    assert '"figure-card"' in block
    assert 'class="chart-card"' not in block
    assert 'figure-caption-row' in block and 'figure-source-chip' in block
    # V3 threads run_id into chart-sourced figures next; V2 already renders
    # the slot conditionally so it lights up without another JS change.
    assert 'c.run_id' in block


def test_loadcharts_wires_figure_run_links():
    i = JS.index("function _loadCharts")
    block = JS[i:i + 2600]
    assert '_wireFigureRunLinks(panel)' in block

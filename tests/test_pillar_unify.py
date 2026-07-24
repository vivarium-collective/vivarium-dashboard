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
    import re
    for p in ("simulate", "visualize"):
        btns = re.findall(r'<button class="study-tab"[^>]*data-pillar="%s"[^>]*>' % p, HTML)
        assert len(btns) == 1, f"{p}: expected 1 member button, got {len(btns)}"
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

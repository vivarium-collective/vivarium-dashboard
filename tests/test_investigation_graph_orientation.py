"""LR<->TB investigation-graph orientation: auto-heuristic + manual toggle wiring.

walkthrough.js isn't node-requirable as a whole (no module.exports, needs a full
DOM) so _renderInvestigationDag's transpose logic is verified here by marker
presence (mirrors tests/test_b4_wiring.py's style for the same file). The pure
`chooseGraphOrientation` heuristic IS node-requirable (lives in aig-graph.js,
which already exports _layoutOptsForBand etc.) and has its own logic test at
tests/js/test_choose_graph_orientation.js (run with `node tests/js/...`).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "vivarium_workbench/static/walkthrough.js").read_text()
AIG_JS = (ROOT / "vivarium_workbench/static/aig-graph.js").read_text()
HTML = (ROOT / "vivarium_workbench/templates/index.html.j2").read_text()


def dag_render_fn():
    """The _renderInvestigationDag function body, up to the next top-level fn."""
    i = JS.index("function _renderInvestigationDag(studies, chainsBySlug, studyEdges)")
    j = JS.index("window._renderInvestigationDag = _renderInvestigationDag;", i)
    return JS[i:j]


def test_choose_graph_orientation_helper_exists_and_is_exported():
    assert "function chooseGraphOrientation(depthCounts)" in AIG_JS
    assert "global.chooseGraphOrientation = chooseGraphOrientation;" in AIG_JS
    assert "chooseGraphOrientation: chooseGraphOrientation" in AIG_JS
    # heuristic branches per spec: shallow/wide -> TB, deep/narrow -> LR
    assert "return 'TB'" in AIG_JS
    assert "return 'LR'" in AIG_JS
    assert "maxDepth <= 2" in AIG_JS
    assert "maxBreadth > maxDepth" in AIG_JS
    assert "maxDepth > maxBreadth" in AIG_JS


def test_render_dag_computes_and_applies_orientation():
    fn = dag_render_fn()
    # auto default comes from the pure helper, keyed on this investigation's depth shape
    assert "window.chooseGraphOrientation" in fn
    assert "depthCounts" in fn
    # manual override (localStorage) wins over auto when present
    assert "_getStoredGraphOrientation(window._currentIset)" in fn
    assert "var orient = _storedOrient ||" in fn
    # both orientation branches are present in the layout + edge-drawing passes
    assert "orient === 'TB'" in fn
    assert fn.count("orient === 'TB'") >= 3, "expected TB branch in layout AND edge-drawing code"


def test_orientation_persistence_helpers_use_localstorage():
    assert "function _graphOrientationKey(name)" in JS
    assert "'aig-orientation:'" in JS
    assert "function _getStoredGraphOrientation(name)" in JS
    assert "window.localStorage.getItem(_graphOrientationKey(name))" in JS
    assert "function _setGraphOrientation(o)" in JS
    assert "window.localStorage.setItem(_graphOrientationKey(window._currentIset), o)" in JS
    assert "window._setGraphOrientation = _setGraphOrientation;" in JS
    # reset-to-auto affordance
    assert "function _resetGraphOrientation()" in JS
    assert "window.localStorage.removeItem(_graphOrientationKey(window._currentIset));" in JS
    assert "window._resetGraphOrientation = _resetGraphOrientation;" in JS


def test_manual_toggle_control_wired_in_template():
    assert 'id="aig-orient-lr"' in HTML
    assert 'id="aig-orient-tb"' in HTML
    assert "window._setGraphOrientation('LR')" in HTML
    assert "window._setGraphOrientation('TB')" in HTML
    # reset-to-auto affordance in the UI
    assert 'id="aig-orient-auto"' in HTML
    assert "window._resetGraphOrientation()" in HTML


def test_tb_edge_endpoints_use_vertical_flow_not_horizontal():
    fn = dag_render_fn()
    i = fn.index("Edges (drawn after positions are known)")
    edges = fn[i:]
    # TB connects parent bottom -> child top (y-based), LR connects
    # parent right -> child left (x-based) — both must be present.
    assert "y1 = pos[pn].y + pos[pn].h;" in edges  # TB: parent's bottom edge
    assert "x1 = pos[pn].x + CARD_W;" in edges     # LR: parent's right edge

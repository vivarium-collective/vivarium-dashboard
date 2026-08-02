# tests/test_study_tabs_structure.py
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "vivarium_workbench/templates/study-detail.html").read_text()


def test_pillar_buttons_present():
    # Top-level study pillars — the `.study-pillars` nav in study-detail.html.
    # Fable A #6 deleted the pillar/member indirection: each `.study-pillar`
    # button now carries the panel `data-kind` directly and calls
    # _setStudyTab(kind) on click (no more separate #study-subnav member row).
    # Pillar name != panel kind for "decide" -> "conclusions"; every other
    # pillar name equals its kind. Task E4 deleted the Exports/data pillar.
    pillar_to_kind = {
        "understand": "overview", "compose": "compose", "simulate": "simulate",
        "readouts": "readouts", "visualize": "visualize", "tests": "tests",
        "decide": "conclusions",
    }
    for pillar, kind in pillar_to_kind.items():
        assert f'data-kind="{kind}"' in HTML and f"_setStudyTab('{kind}')" in HTML, \
            f"pillar {pillar!r} -> kind {kind!r} not wired"
    assert 'data-kind="data"' not in HTML


def test_subnav_container_removed():
    assert 'id="study-subnav"' not in HTML


def test_every_pillar_button_has_a_kind_and_calls_set_study_tab():
    # Task E4 dropped the Exports/data pillar: 8 -> 7 buttons.
    import re
    btns = re.findall(r'<button class="study-pillar[^"]*"[^>]*>', HTML)
    assert len(btns) == 7, f"expected 7 pillar buttons, got {len(btns)}"
    for b in btns:
        assert "data-kind=" in b, f"pillar button missing data-kind: {b[:80]}"
    assert re.search(r'onclick="_setStudyTab\(', HTML), "pillar buttons must call _setStudyTab directly"
    assert "_setStudyPillar(" not in HTML


def test_panels_unchanged_all_eleven_present():
    for kind in ["overview", "build", "simulations", "baseline", "observables",
                 "variants", "interventions", "runs", "tests", "visualizations", "conclusions"]:
        assert f'data-kind="{kind}"' in HTML and f'id="panel-{kind}"' in HTML


def test_deep_link_onclicks_preserved():
    assert "_setStudyTab('tests')" in HTML or "_setStudyTab(\\'tests\\'" in HTML
    assert "_setStudyTab('conclusions')" in HTML or "_setStudyTab(\\'conclusions\\'" in HTML


def test_js_pillar_indirection_removed():
    # Fable A #6: _setStudyPillar / _showPillarSubnav / _pillarForKind deleted;
    # _setStudyTab is the single tab switcher and toggles `.study-pillar`
    # buttons directly (there's no separate subnav row to toggle anymore).
    js = (ROOT / "vivarium_workbench/static/study-detail.js").read_text()
    for fn in ("_setStudyPillar", "_showPillarSubnav", "_pillarForKind"):
        assert fn not in js, f"{fn} should have been deleted from study-detail.js"
    assert "function _setStudyTab" in js
    assert "window._setStudyTab" in js
    i = js.index("function _setStudyTab")
    block = js[i:i + 600]
    assert "querySelectorAll('.study-pillar')" in block


def test_css_styles_pillars():
    css = (ROOT / "vivarium_workbench/static/style.css").read_text()
    assert ".study-pillar" in css

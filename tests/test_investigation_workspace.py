from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "vivarium_workbench/static/walkthrough.js").read_text(encoding="utf-8")
TPL = (ROOT / "vivarium_workbench/templates/index.html.j2").read_text(encoding="utf-8")


def test_studies_grouped_by_investigation():
    # _renderStudyBrowseCards groups by investigation (not one flat "All studies").
    i = JS.index("function _renderStudyBrowseCards")
    block = JS[i:i + 2500]
    assert "data-study-group" in block          # one group per investigation
    assert "__ungrouped__" in block             # bucket for studies with no iset
    assert "All studies" not in block           # the old single flat group is gone


def test_explore_tab_row_has_counts():
    assert 'id="iset-tab-inv-count"' in TPL
    assert 'id="iset-tab-study-count"' in TPL
    assert "Explore" in TPL                      # the surface label


def test_workspace_regions_exist():
    for _id in ['iset-explore', 'iset-workspace', 'ws-back', 'ws-title',
                'ws-context', 'ws-context-bar', 'ws-study-tabs', 'ws-study-frame']:
        assert 'id="%s"' % _id in TPL, _id


def test_explore_workspace_toggle_functions():
    assert "function _showExplore" in JS
    assert "function _showWorkspace" in JS
    assert "window._showExplore" in JS
    assert "window._showWorkspace" in JS


def test_context_collapse_function():
    assert "function _setInvestigationContextCollapsed" in JS
    assert "ws-context-bar" in JS
    # the slim bar's onclick re-expands
    assert "_setInvestigationContextCollapsed(false)" in TPL


def test_study_tabs_manager():
    for fn in ["_wsOpenStudyTab", "_wsCloseStudyTab", "_wsRenderStudyTabs", "_wsResetStudyTabs"]:
        assert "function %s" % fn in JS, fn
        assert "window.%s" % fn in JS, fn
    # opening a tab collapses the context; closing the last returns to graph-only
    o = JS[JS.index("function _wsOpenStudyTab"): JS.index("function _wsOpenStudyTab") + 900]
    assert "_setInvestigationContextCollapsed(true)" in o
    c = JS[JS.index("function _wsCloseStudyTab"): JS.index("function _wsCloseStudyTab") + 900]
    assert "_setInvestigationContextCollapsed(false)" in c


# ── Task 5: consistency router + investigation-workspace render ──────────────

def test_router_uses_workspace_not_legacy():
    assert "function _showInvestigationWorkspace" in JS
    r = JS[JS.index("function _openStudyEmbeddedNewTab"): JS.index("function _openStudyEmbeddedNewTab") + 1200]
    assert "_showInvestigationWorkspace" in r        # loads the study's own investigation
    assert "_wsOpenStudyTab" in r                    # opens/focuses the tab
    assert "_selectStudyInRail" in r                 # reflects selection in the rail
    assert "window.location = _studyHref" not in r   # no dead-end full-window nav
    assert "window.location" not in r                # no full-window navigation at all
    assert "_openInvestigation(" not in r            # never the legacy icon-view path


def test_showworkspace_renders_graph_not_legacy_icon_view():
    w = JS[JS.index("function _showInvestigationWorkspace"): JS.index("function _showInvestigationWorkspace") + 1200]
    assert "ws-context" in w
    assert "_showWorkspace" in w
    assert "_wsResetStudyTabs" in w
    assert "_openInvestigation(" not in w            # never the legacy icon-view path


def test_investigation_open_entry_points_route_to_workspace():
    # The card onclick and the rail entry point open the workspace, not the
    # legacy focus-mode render.
    assert 'onclick="_showInvestigationWorkspace(' in JS
    rail = JS[JS.index("function _vivOpenInvestigationFromRail"): JS.index("function _vivOpenInvestigationFromRail") + 500]
    assert "_showInvestigationWorkspace" in rail

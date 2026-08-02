"""Task E2: fold the two study-level bulk-download groups (analysis result
files `#data-files` + the raw-simulation-data bulk `#raw-data-list` /
`#exports-downloads`) out of the Exports tab (`data-kind="data"`) and onto
the Simulations tab (`data-kind="simulate"`) as a compact "Study artifacts"
strip. Same element ids so the existing loaders (`_loadAnalysisOutputs`,
`_loadRawData`, `_downloadAllRawExports`) bind unchanged; the loader triggers
move from the `data` tab-activation branch to the `simulate` one; the C4
Readouts pointer repoints from `_gotoStudyTab('data', 'exports-downloads')`
to `_gotoStudyTab('simulate', 'exports-downloads')`.

See .superpowers/sdd/fable-increment-a/task-E2-brief.md.
"""
from __future__ import annotations

import pathlib
import tempfile
from pathlib import Path

from vivarium_workbench.lib.study_page import render_study_detail_html

_PKG = Path(__file__).parent.parent / "vivarium_workbench"


def _render(spec_extra=None):
    spec = {"name": "s1"}
    if spec_extra:
        spec.update(spec_extra)
    with tempfile.TemporaryDirectory() as d:
        return render_study_detail_html(pathlib.Path(d), "s1", spec)


def _panel(html: str, kind: str) -> str:
    # Anchor on the panel's `id="panel-<kind>"`, not `data-kind="<kind>"` —
    # the `.study-pillar` tab BUTTON also carries `data-kind="<kind>"` and
    # appears earlier in the document, which would mis-anchor the slice.
    i = html.index('id="panel-%s"' % kind)
    nxt = html.find('class="study-tab-panel"', i + 10)
    return html[i: nxt if nxt != -1 else len(html)]


# ---------------------------------------------------------------------------
# Template: both groups render under Simulations, not under Exports.
# ---------------------------------------------------------------------------

def test_analysis_files_group_moved_to_simulate_panel():
    html = _render()
    sim_panel = _panel(html, "simulate")
    assert 'id="data-files"' in sim_panel
    assert 'id="data-download-all"' in sim_panel
    assert '/api/study-analysis-zip?study=s1' in sim_panel
    # Task E4 deleted the Exports/data tab entirely — nothing to check it
    # against anymore; the group now has exactly one home (Simulations).
    assert 'id="panel-data"' not in html


def test_raw_data_bulk_group_moved_to_simulate_panel():
    html = _render()
    sim_panel = _panel(html, "simulate")
    assert 'id="raw-data-list"' in sim_panel
    assert 'id="exports-downloads"' in sim_panel
    assert 'id="raw-data-download-all"' in sim_panel
    assert 'onclick="_downloadAllRawExports()"' in sim_panel
    # Task E4 deleted the Exports/data tab entirely — nothing to check it
    # against anymore; the group now has exactly one home (Simulations).
    assert 'id="panel-data"' not in html


def test_simulate_panel_still_has_runs_table_and_run_detail():
    """Sanity: the strip is additive — the existing runs UI is untouched."""
    html = _render()
    sim_panel = _panel(html, "simulate")
    assert 'id="study-sim-table"' in sim_panel
    assert 'id="study-run-detail"' in sim_panel


# ---------------------------------------------------------------------------
# JS: loader triggers move from the 'data' tab-activation branch to
# 'simulate'.
# ---------------------------------------------------------------------------

def _set_study_tab_body(js: str) -> str:
    i = js.index("function _setStudyTab(")
    j = js.index("window._setStudyTab", i)
    return js[i:j]


def test_loaders_trigger_on_simulate_tab_activation():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    body = _set_study_tab_body(js)
    i = body.index("kind === 'simulate'")
    line = body[i - 10: i + 120]
    assert "_loadAnalysisOutputs()" in line
    assert "_loadRawData()" in line


def test_loaders_no_longer_trigger_on_data_tab_activation():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    body = _set_study_tab_body(js)
    assert "kind === 'data'" not in body


# ---------------------------------------------------------------------------
# The C4 Readouts pointer now targets the simulate tab, not the (soon-dead)
# data tab.
# ---------------------------------------------------------------------------

def test_readouts_pointer_targets_simulate_tab_not_data_tab():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    i = js.index("function _loadReadoutsDownloadPointer(")
    j = js.index("window._loadReadoutsDownloadPointer", i)
    body = js[i:j]
    assert "_gotoStudyTab(\\'simulate\\'" in body
    assert "exports-downloads" in body
    assert "_gotoStudyTab(\\'data\\'" not in body


def test_no_remaining_jump_targets_data_tab_for_downloads():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    assert "_gotoStudyTab(\\'data\\'" not in js
    assert "_gotoStudyTab('data'" not in js


# ---------------------------------------------------------------------------
# Out of scope (E3): per-row run "Data" links + _showRunDetail untouched.
# ---------------------------------------------------------------------------

def test_per_row_data_links_and_show_run_detail_untouched():
    sim_table_js = (_PKG / "static" / "sim-table.js").read_text(encoding="utf-8")
    assert "/api/simulation-run-download?run_id=" in sim_table_js
    study_detail_js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    assert "function _showRunDetail(" in study_detail_js


def test_js_syntax_valid():
    import subprocess
    r = subprocess.run(
        ["node", "--check", str(_PKG / "static" / "study-detail.js")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr

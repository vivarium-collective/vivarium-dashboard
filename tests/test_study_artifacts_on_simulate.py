"""Study-spine reorg (Slice 1, spec §1/§3.2/§3.3/§3.4): the two study-level
bulk-download groups that Task E2 previously folded onto the Simulations tab
(analysis result files `#data-files` + the raw-simulation-data bulk
`#raw-data-list` / `#exports-downloads`) split into their own Evidence
panels: analysis result files -> Analyses (`data-kind="analyses"`), raw
simulation data -> Results (`data-kind="results"`). Same element ids so the
existing loaders (now `_loadAnalyses`, `_loadResults`, and unchanged
`_downloadAllRawExports`) bind unchanged; the loader triggers move from the
`simulate` tab-activation branch onto their own `analyses`/`results`
branches. The Readouts pointer repoints from
`_gotoStudyTab('simulate', 'exports-downloads')` to
`_gotoStudyTab('results', 'exports-downloads')`.

See docs/superpowers/specs/2026-08-16-study-spine-reorg-design.md (§3.2-3.4)
and docs/superpowers/plans/2026-08-16-study-spine-reorg.md (Task 1).
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
# Template: each group renders under its own Evidence panel, not Simulations.
# ---------------------------------------------------------------------------

def test_analysis_files_group_moved_to_analyses_panel():
    html = _render()
    analyses_panel = _panel(html, "analyses")
    assert 'id="data-files"' in analyses_panel
    assert 'id="data-download-all"' in analyses_panel
    assert '/api/study-analysis-zip?study=s1' in analyses_panel
    sim_panel = _panel(html, "simulate")
    assert 'id="data-files"' not in sim_panel
    assert 'id="data-download-all"' not in sim_panel


def test_raw_data_bulk_group_moved_to_results_panel():
    html = _render()
    results_panel = _panel(html, "results")
    assert 'id="raw-data-list"' in results_panel
    assert 'id="exports-downloads"' in results_panel
    assert 'id="raw-data-download-all"' in results_panel
    assert 'onclick="_downloadAllRawExports()"' in results_panel
    sim_panel = _panel(html, "simulate")
    assert 'id="raw-data-list"' not in sim_panel
    assert 'id="exports-downloads"' not in sim_panel


def test_simulate_panel_still_has_runs_table_and_run_detail():
    """Sanity: relocation is subtractive on Simulations only for the
    artifacts strip — the existing runs UI is untouched."""
    html = _render()
    sim_panel = _panel(html, "simulate")
    assert 'id="study-sim-table"' in sim_panel
    assert 'id="study-run-detail"' in sim_panel


def test_results_and_analyses_pillars_under_evidence_cluster():
    html = _render()
    i = html.index('data-act="evidence"')
    j = html.index('data-act="assurance"', i)
    evidence = html[i:j]
    assert 'data-kind="results"' in evidence
    assert 'data-kind="analyses"' in evidence
    assert 'data-kind="visualize"' in evidence
    # Order: Results, Analyses, Visualizations.
    assert evidence.index('data-kind="results"') < evidence.index('data-kind="analyses"') < evidence.index('data-kind="visualize"')


def test_simulate_pillar_moved_under_design_cluster():
    html = _render()
    i = html.index('data-act="design"')
    j = html.index('data-act="evidence"', i)
    design = html[i:j]
    assert 'data-kind="simulate"' in design
    i2 = html.index('data-act="evidence"')
    j2 = html.index('data-act="assurance"', i2)
    evidence = html[i2:j2]
    assert 'data-kind="simulate"' not in evidence


# ---------------------------------------------------------------------------
# JS: loader triggers fire on their own tab-activation branches.
# ---------------------------------------------------------------------------

def _set_study_tab_body(js: str) -> str:
    i = js.index("function _setStudyTab(")
    j = js.index("window._setStudyTab", i)
    return js[i:j]


def test_loaders_trigger_on_their_own_tab_activation():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    body = _set_study_tab_body(js)
    i = body.index("kind === 'analyses'")
    assert "_loadAnalyses()" in body[i - 10: i + 60]
    j = body.index("kind === 'results'")
    assert "_loadResults()" in body[j - 10: j + 60]
    k = body.index("kind === 'simulate'")
    line = body[k - 10: k + 60]
    assert "_loadAnalyses()" not in line
    assert "_loadResults()" not in line


def test_loaders_no_longer_trigger_on_data_tab_activation():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    body = _set_study_tab_body(js)
    assert "kind === 'data'" not in body


# ---------------------------------------------------------------------------
# The C4 Readouts pointer now targets the results tab.
# ---------------------------------------------------------------------------

def test_readouts_pointer_targets_results_tab():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    i = js.index("function _loadReadoutsDownloadPointer(")
    j = js.index("window._loadReadoutsDownloadPointer", i)
    body = js[i:j]
    assert "_gotoStudyTab(\\'results\\'" in body
    assert "exports-downloads" in body
    assert "_gotoStudyTab(\\'data\\'" not in body
    assert "_gotoStudyTab(\\'simulate\\'" not in body


def test_no_remaining_jump_targets_data_tab_for_downloads():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    assert "_gotoStudyTab(\\'data\\'" not in js
    assert "_gotoStudyTab('data'" not in js


# ---------------------------------------------------------------------------
# Out of scope: per-row run "Data" links + _showRunDetail untouched.
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

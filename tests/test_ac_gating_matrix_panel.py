"""Investigation report: the AC → study gating-matrix panel.

The report (``lib.investigation_report`` + template) renders an acceptance-criteria
→ study gating matrix: rows = acceptance criteria, the gating study (linked) + the
code-computed result, and criteria with NO ``study:`` link are FLAGGED
("no study linked — gap"). Unlike the old client panel (which fetched
``/api/linkage-index`` live), the matrix is now computed server-side by
``linkage_index.ac_gating_matrix`` and embedded in the report data — see
``test_investigation_report.py`` for the data-shape coverage. These assert the
template's render source.
"""
from __future__ import annotations

from pathlib import Path

_TPL = (
    Path(__file__).parent.parent / "vivarium_workbench" / "templates" / "investigation-report.html"
).read_text(encoding="utf-8")


def test_panel_present_and_built():
    assert "ac-gating-matrix" in _TPL
    assert "_acGatingMatrixHtml" in _TPL


def test_panel_built_from_server_computed_matrix():
    # Built from the embedded, server-computed matrix (linkage_index), not a
    # live browser fetch.
    assert "ac_matrix" in _TPL


def test_panel_flags_unlinked_acceptance_gap():
    assert "no study linked — gap" in _TPL
    # The gap-count footnote.
    assert "have no study linked (gaps)" in _TPL


def test_panel_rows_link_studies_and_show_results():
    # Linked criteria link to their per-study section + show a result badge.
    assert "#s-" in _TPL
    assert "_acResultBadge" in _TPL

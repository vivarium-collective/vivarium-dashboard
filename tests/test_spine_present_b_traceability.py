"""Thread-B / Task 2 (B1): finding ↔ test ↔ run ↔ band traceability.

Structural tests (no JS harness): the report's `_renderFinding` and the study
page's finding cards must render `evidence.from_test` / `from_run` as clickable
anchors (not plain <code>), surface the dropped computed `divergence_factor`
and `provenance.run_ids` (linked), and inline the cited test's pass_if band.
"""
from __future__ import annotations

from pathlib import Path

_PKG = Path(__file__).parent.parent / "vivarium_workbench"


def test_report_finding_traceability():
    # The report (lib.investigation_report + template) anchors a finding's
    # from_test to its test card via the prefix helper, inlines the cited
    # pass_if band, surfaces the computed divergence, and lists run_ids as plain
    # code (no dangling #run- anchors, since the report has no per-run rows).
    tpl = (_PKG / "templates" / "investigation-report.html").read_text(encoding="utf-8")
    assert "_traceLink" in tpl
    assert "'#test-'" not in tpl  # built via the prefix helper, not literal
    assert "_traceLink('test'" in tpl  # the TEST reference is anchored
    assert "finding-traceability" in tpl
    # The headline computed number is surfaced.
    assert "divergence_factor" in tpl
    assert "finding-divergence" in tpl
    assert "vs expected" in tpl
    # provenance.run_ids surfaced + the cited test's pass_if band inlined.
    assert "run_ids" in tpl
    assert "pass_if-band" in tpl
    # report test rows are anchor targets for from_test.
    assert 'id="test-' in tpl
    # Run references are plain <code>, never dangling #run- anchors.
    assert 'href="#run-' not in tpl
    assert "'#run-'" not in tpl
    assert "#run-" not in tpl
    # ...while the resolvable #test- anchors are built by the helper.
    assert "prefix + '-'" in tpl


def test_study_page_finding_traceability():
    html = (_PKG / "templates" / "study-detail.html").read_text(encoding="utf-8")
    # from_test / from_run are clickable anchors to the test/run cards.
    assert 'href="#bt-{{ _ftok }}"' in html
    assert 'href="#run-{{ _rtok }}"' in html
    # The study page DOES emit the matching anchor targets, so its #run-/#bt-
    # links resolve (unlike the report, which has no per-run rows).
    assert 'id="run-' in html
    assert 'id="bt-' in html
    # divergence_factor + provenance.run_ids surfaced; pass_if band inlined.
    assert "divergence_factor" in html
    assert "finding-divergence" in html
    assert "run_ids" in html
    assert "pass_if-band" in html

"""Slice 3: the Audit tab's Sourcing sub-panel renders where a model came
from (reuse / compose / build-new) and the module_sourcing audit of that
choice. JS-string scan, matching the repo's existing JS-scan test style
(see test_scorecard_margin_render.py / testing/test_modular_tests_js.py),
plus a template-mount assertion.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vivarium_workbench"
JS = (ROOT / "static" / "study-detail.js").read_text(encoding="utf-8")
TPL = (ROOT / "templates" / "study-detail.html").read_text(encoding="utf-8")


def test_sourcing_loader_present():
    assert "_loadAuditSourcing" in JS
    assert "_sourcingCheckGroupHtml" in JS
    # reads the study spec's own sourcing block off window._study (no fetch)
    assert "spec.sourcing" in JS
    assert "audit-sourcing" in JS


def test_sourcing_dispatched_from_audit_tab():
    # _loadAudit must fill the sourcing sub-panel alongside the three groups
    audit_fn = JS[JS.index("function _loadAudit(spec)"):]
    body = audit_fn[: audit_fn.index("window._loadAudit")]
    assert "_loadAuditSourcing(spec)" in body


def test_sourcing_axes_reuse_verdict_vocabulary():
    # the four stable axis IDs render through the shared axis renderer
    for axis in ("source_fit", "reinvention", "novelty_justified", "survey_recorded"):
        assert axis in JS
    # reuses _renderAuditSufficiencyAxis + the within_tol/drift/mismatch map
    assert "_renderAuditSufficiencyAxis" in JS
    assert "_AUDIT_GATE_COLORS" in JS


def test_sourcing_decision_and_gate_surfaced():
    assert "sourcing-decision" in JS       # decision + modules + requires summary line
    assert "catches_if_wrong" in JS        # what the audit would have caught
    assert "gate: " in JS


def test_sourcing_mount_in_audit_panel_template():
    # mount lives inside the Audit panel's checks-band
    panel = TPL[TPL.index('id="panel-audit"'):]
    panel = panel[: panel.index("</section>")]
    assert 'id="audit-sourcing"' in panel
    assert "check-group-sourcing" in panel

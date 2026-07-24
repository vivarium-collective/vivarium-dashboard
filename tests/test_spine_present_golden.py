"""Thread-A golden — READ-ONLY against the real v2e-invest workspace.

Confirms the three surfaced computed artifacts actually reach the data layer on
real spine output:
- _report_lint returns the readout-migration (SP2b-ii) + band-citation-gap
  (SP2c) findings for the real studies.
- _study_detail_spec carries computed_gate_verdict.
- the iset response carries computed_acceptance with per-criterion entries.

Skipped when v2e-invest is not checked out. NEVER writes to v2e-invest.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vivarium_workbench.lib.report_views import build_iset_detail, build_report_lint
from vivarium_workbench.lib.study_spec import load_study_detail_spec

_V2E = Path("/Users/eranagmon/code/v2e-invest")
pytestmark = pytest.mark.skipif(
    not (_V2E / "workspace.yaml").is_file(),
    reason="v2e-invest workspace not checked out",
)


def _dirty_count() -> int:
    out = subprocess.run(
        ["git", "-C", str(_V2E), "status", "--porcelain"],
        capture_output=True, text=True,
    )
    return len([ln for ln in out.stdout.splitlines() if ln.strip()])


@pytest.fixture
def v2e_workspace():
    return _V2E


def test_golden_report_lint_returns_real_findings(v2e_workspace):
    before = _dirty_count()
    d, code = build_report_lint(_V2E)
    assert code == 200
    findings = d["findings"]
    assert findings, "real workspace should yield lint findings"
    checks = {f["check"] for f in findings}
    # SP2b-ii readout-migration + SP2c band-citation-gap are surfaced
    assert any("readout" in c for c in checks), checks
    assert "band_test_missing_cites" in checks, checks
    for f in findings:
        assert {"study", "check", "severity", "message"} <= set(f)
    assert _dirty_count() == before, "report-lint must not write to v2e-invest"


def test_golden_study_detail_carries_computed_gate_verdict(v2e_workspace):
    before = _dirty_count()
    # Discover real study slugs via the workspace layout (studies may live under
    # a relocated dir, e.g. workspace/studies, per workspace.yaml's `layout:`).
    from vivarium_workbench.lib.workspace_paths import WorkspacePaths
    studies_dir = WorkspacePaths.load(_V2E).studies
    studies = sorted(p.name for p in studies_dir.iterdir()
                     if (p / "study.yaml").is_file())
    assert studies, "v2e-invest should have studies"
    # Find one that carries a code-evaluated gate verdict (not every study runs
    # its gate); the contract is that the surfaced artifact reaches the data layer.
    found = None
    for slug in studies:
        spec = load_study_detail_spec(_V2E, slug)
        cgv = (spec or {}).get("computed_gate_verdict")
        if cgv and cgv.get("evaluated_by") == "code":
            found = cgv
            break
    assert found is not None, "at least one study should carry a code-computed gate verdict"
    assert _dirty_count() == before, "study detail must not write to v2e-invest"


def test_golden_iset_carries_computed_acceptance(v2e_workspace):
    before = _dirty_count()
    invs = sorted(p.name for p in (_V2E / "investigations").iterdir()
                  if (p / "investigation.yaml").is_file())
    assert invs, "v2e-invest should have investigations"
    # Find one whose computed_acceptance has criteria.
    found = False
    for inv in invs:
        data = build_iset_detail(_V2E, inv)
        ca = (data or {}).get("computed_acceptance")
        if ca and ca.get("criteria"):
            found = True
            assert "verdict_status" in ca
            break
    assert found, "at least one investigation should carry computed_acceptance criteria"
    assert _dirty_count() == before, "iset detail must not write to v2e-invest"

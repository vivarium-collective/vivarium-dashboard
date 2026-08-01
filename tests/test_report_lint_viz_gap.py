"""Task V4 — the 'visualization_gap' readiness finding + its wiring into
GET /api/report-lint (feeding the existing "N readiness gaps" pill).

Mirrors ``tests/test_report_lint_question.py``'s style for the lib-level
findings builder, plus a live-server test (via the ``dashboard_client``
factory) confirming the finding actually rides ``/api/report-lint`` and is
counted the same way the readiness panel counts gaps: ``severity in
{"warning", "error"}`` (see ``static/study-detail.js``'s
``_renderReadinessPanel``, which sums ``sev.error + sev.warning`` into the
"N readiness gaps" pill; "info" findings are notes, not gaps).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib.report_views import (
    _visualization_gap_findings,
    build_report_lint,
)


def _study_with_no_figures(ws_root: Path, slug: str = "no-viz") -> None:
    sd = ws_root / "studies" / slug
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text(
        yaml.safe_dump({"name": slug, "purpose": {"question": "Does X hold?"}}),
        encoding="utf-8",
    )


def test_non_qualifying_study_yields_visualization_gap_finding(tmp_path):
    ws = tmp_path / "ws"
    _study_with_no_figures(ws)
    findings = _visualization_gap_findings(ws)
    checks = [f["check"] for f in findings]
    assert "visualization_gap" in checks
    f = next(f for f in findings if f["check"] == "visualization_gap")
    assert f["study"] == "no-viz"
    assert f["severity"] in ("warning", "warn")
    assert f["field_path"] == "visualizations"
    # actionable — names what to do, not just that something's wrong
    assert "add" in f["message"].lower() or "link" in f["message"].lower()


def test_qualifying_study_yields_no_finding(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    _study_with_no_figures(ws, slug="has-viz")

    from vivarium_workbench.lib import viz_gate as _viz_gate
    monkeypatch.setattr(
        _viz_gate, "study_visualization_status",
        lambda ws_root, slug: {
            "has_interactive": True, "has_run_linked": True,
            "qualifies": True, "n_figures": 1, "reason": None,
        },
    )
    findings = _visualization_gap_findings(ws)
    assert [f for f in findings if f["check"] == "visualization_gap"] == []


def test_visualization_gap_findings_never_raises_on_unreadable_study(tmp_path, monkeypatch):
    """A study whose viz-status probe blows up must not 500 the lint — it
    reads as a (soft) gap, not a crash."""
    ws = tmp_path / "ws"
    _study_with_no_figures(ws, slug="broken")

    from vivarium_workbench.lib import viz_gate as _viz_gate

    def _boom(ws_root, slug):
        raise RuntimeError("composite cannot be resolved")

    monkeypatch.setattr(_viz_gate, "study_visualization_status", _boom)
    findings = _visualization_gap_findings(ws)  # must not raise
    checks = [f["check"] for f in findings]
    assert "visualization_gap" in checks


def test_build_report_lint_includes_visualization_gap(tmp_path):
    ws = tmp_path / "ws"
    _study_with_no_figures(ws)
    body, code = build_report_lint(ws)
    assert code == 200
    checks = [f["check"] for f in body["findings"]]
    assert "visualization_gap" in checks


def test_visualization_gap_is_soft_never_error(tmp_path):
    """The finding must never be a hard error/block — warn/info only."""
    ws = tmp_path / "ws"
    _study_with_no_figures(ws)
    findings = _visualization_gap_findings(ws)
    for f in findings:
        assert f["severity"] != "error"


# ---------------------------------------------------------------------------
# Live-server: the finding rides /api/report-lint and is counted the same
# way the readiness panel counts "N readiness gaps" (severity warning/error).
# ---------------------------------------------------------------------------

def test_rides_report_lint_endpoint_and_counts_as_a_readiness_gap(dashboard_client, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text("name: viz-gap-ws\n", encoding="utf-8")
    _study_with_no_figures(ws, slug="no-viz")

    client = dashboard_client(ws)
    r = client.get("/api/report-lint")
    assert r.status_code == 200
    findings = r.json()["findings"]
    study_findings = [f for f in findings if f.get("study") == "no-viz"]
    viz_findings = [f for f in study_findings if f.get("check") == "visualization_gap"]
    assert viz_findings, f"expected a visualization_gap finding; got: {study_findings}"

    # Same arithmetic the readiness panel uses (_renderReadinessPanel in
    # static/study-detail.js): gaps = count(severity in {error, warning}).
    gaps = sum(1 for f in study_findings if f.get("severity") in ("error", "warning"))
    assert gaps >= 1, "visualization_gap finding should be counted in N readiness gaps"

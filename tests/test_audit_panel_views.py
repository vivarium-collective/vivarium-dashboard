"""Tests for the Assurance › Audit "Sufficiency" worker
(`lib/audit_panel_views.build_study_test_audit`).

Mirrors `test_audit_views.py`'s availability gate: the workbench pins
pbg-superpowers bare from PyPI, so `viva_superpowers.test_audit` only lights
up once a viva-superpowers release (or a git pin) includes it. When absent,
`build_study_test_audit` degrades to a 200 `{"unavailable": true, ...}` body
— that is the contract these tests must hold in BOTH worlds; the
populated-report specifics are gated on availability.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib.audit_panel_views import build_study_test_audit


def _has_test_audit() -> bool:
    try:
        import viva_superpowers.test_audit  # noqa: F401
    except Exception:
        return False
    return True


_HAS_TEST_AUDIT = _has_test_audit()


def _make_workspace(tmp_path: Path, slug: str = "s1", *, behavior_tests=None) -> Path:
    ws = tmp_path / "ws"
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: probe-ws\n", encoding="utf-8")
    spec = {
        "schema_version": 3,
        "name": slug,
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
    }
    if behavior_tests is not None:
        spec["behavior_tests"] = behavior_tests
    (sd / "study.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return ws


def test_missing_study_param_is_400(tmp_path):
    ws = _make_workspace(tmp_path)
    body, status = build_study_test_audit(ws, "")
    assert status == 400
    assert "error" in body


def test_unknown_study_is_404(tmp_path):
    ws = _make_workspace(tmp_path)
    body, status = build_study_test_audit(ws, "does-not-exist")
    assert status == 404
    assert "error" in body


def test_build_study_test_audit_returns_200_dict(tmp_path):
    ws = _make_workspace(tmp_path)
    body, status = build_study_test_audit(ws, "s1")
    assert status == 200
    assert isinstance(body, dict)


def test_build_study_test_audit_returns_sufficiency_axes_and_gate(tmp_path):
    """The core requirement: for a fixture study, the payload carries the
    sufficiency axes (discrimination, objective_coverage, redundancy,
    discriminating_control, band_provenance) from
    `viva_superpowers.test_audit.build_audit_report`, plus a top-level
    `gate` (pass/warn/fail) from `audit_gate`."""
    if not _HAS_TEST_AUDIT:
        import pytest
        pytest.skip("viva_superpowers.test_audit not importable in this environment")

    ws = _make_workspace(tmp_path, behavior_tests=[
        {
            "name": "daughters_hydrated",
            "classification": "primary",
            "measure": {"path": "agents.*.mass"},
            "pass_if": {"low": 0.9, "high": 1.1},
            "cites": ["some-paper"],
        },
    ])
    body, status = build_study_test_audit(ws, "s1")
    assert status == 200
    assert body.get("unavailable") is not True, body

    assert body.get("schema") == "report_card_verdict/v2"
    assert body.get("gate") in ("pass", "warn", "fail")

    groups = body.get("groups") or {}
    sufficiency_ids = {ax.get("id") for ax in (groups.get("sufficiency") or {}).get("axes", [])}
    assert sufficiency_ids == {
        "discrimination", "objective_coverage", "redundancy", "discriminating_control",
    }
    provenance_ids = {ax.get("id") for ax in (groups.get("provenance") or {}).get("axes", [])}
    assert "band_provenance" in provenance_ids


def test_degrades_gracefully_never_500(tmp_path, monkeypatch):
    """An import/scoring failure degrades to a 200 unavailable(reason) body
    — never propagates an exception (§2 R2, absent != empty)."""
    import vivarium_workbench.lib.audit_panel_views as mod

    ws = _make_workspace(tmp_path)

    class _Boom:
        @staticmethod
        def build_audit_report(spec):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "vivarium_workbench.lib.study_spec.load_study_detail_spec",
        lambda ws_root, slug: {"name": slug},
    )

    import sys
    import types
    fake_pkg = types.ModuleType("viva_superpowers")
    fake_pkg.test_audit = _Boom()
    monkeypatch.setitem(sys.modules, "viva_superpowers", fake_pkg)
    monkeypatch.setitem(sys.modules, "viva_superpowers.test_audit", _Boom())

    body, status = mod.build_study_test_audit(ws, "s1")
    assert status == 200
    assert body.get("unavailable") is True
    assert "reason" in body

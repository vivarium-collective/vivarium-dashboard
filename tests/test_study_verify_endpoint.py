"""Tests for ``POST /api/study-verify``
(``lib.study_verify_views.study_verify``).

Rewire-first: this endpoint wraps
``viva_superpowers.study_verify.verify_study`` unchanged — the plugin still
runs the static cross-reference checks; only the caller (the workbench, on
behalf of ``/viva-study verify``) moves off shelling out to
``python -m viva_superpowers.study_verify``. These tests exercise the lib
builder directly (the same "endpoint test calls the lib fn" idiom as
``test_study_findings_populate_endpoint.py``) plus an equivalence check against
calling ``verify_study`` directly.
"""
from pathlib import Path

import pytest

from vivarium_workbench.lib import study_verify_views as views

# A study whose `knockout` variant references a baseline that isn't declared
# (`base_composite: ghost-baseline`) → verify_study emits a `variant-base-
# unknown` ERROR finding. Everything else resolves cleanly.
DIRTY_STUDY_YAML = """\
name: verify-dirty
objective: |
  A study with a dangling variant base.
baseline:
  name: wt
  composite: my_project.core.baseline
variants:
  - name: knockout
    base_composite: ghost-baseline
"""

# A structurally clean study: the variant references the declared baseline by
# name, no dangling refs → zero findings.
CLEAN_STUDY_YAML = """\
name: verify-clean
objective: |
  A fully consistent study.
baseline:
  name: wt
  composite: my_project.core.baseline
variants:
  - name: knockout
    base_composite: wt
"""


def _study_ws(tmp_path: Path, text: str, slug: str) -> tuple[Path, Path]:
    ws = tmp_path / "ws"
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: verify-test\n")
    (ws / ".pbg").mkdir(exist_ok=True)
    sy = sd / "study.yaml"
    sy.write_text(text)
    return ws, sy


def test_missing_study_400(tmp_path):
    ws, _ = _study_ws(tmp_path, CLEAN_STUDY_YAML, "verify-clean")
    body, status = views.study_verify(ws, {})
    assert status == 400
    assert "study" in body["error"]


def test_unknown_study_404(tmp_path):
    ws, _ = _study_ws(tmp_path, CLEAN_STUDY_YAML, "verify-clean")
    body, status = views.study_verify(ws, {"study": "does-not-exist"})
    assert status == 404
    assert "does-not-exist" in body["error"]


def test_dirty_study_produces_finding(tmp_path):
    ws, sy = _study_ws(tmp_path, DIRTY_STUDY_YAML, "verify-dirty")

    body, status = views.study_verify(ws, {"study": "verify-dirty"})

    assert status == 200
    assert body["study"] == "verify-dirty"
    assert body["study_yaml"] == str(sy)

    findings = body["findings"]
    assert isinstance(findings, list)
    assert len(findings) >= 1
    checks = {f["check"] for f in findings}
    assert "variant-base-unknown" in checks
    # each finding carries the VerifyFinding shape.
    f0 = next(f for f in findings if f["check"] == "variant-base-unknown")
    assert set(f0) == {"level", "check", "field_path", "message"}
    assert f0["level"] == "error"

    summary = body["summary"]
    assert isinstance(summary, dict)
    assert set(summary) == {"error", "warning", "info"}
    assert summary["error"] >= 1


def test_clean_study_zero_findings(tmp_path):
    ws, _ = _study_ws(tmp_path, CLEAN_STUDY_YAML, "verify-clean")

    body, status = views.study_verify(ws, {"study": "verify-clean"})

    assert status == 200
    assert body["study"] == "verify-clean"
    assert body["findings"] == []
    assert body["summary"] == {"error": 0, "warning": 0, "info": 0}


def test_equivalence_with_direct_verify_call(tmp_path):
    """The endpoint's findings must match calling
    ``viva_superpowers.study_verify.verify_study`` directly."""
    pbg_study_verify = pytest.importorskip("viva_superpowers.study_verify")

    ws, sy = _study_ws(tmp_path, DIRTY_STUDY_YAML, "verify-dirty")

    endpoint_body, status = views.study_verify(ws, {"study": "verify-dirty"})
    assert status == 200

    direct = pbg_study_verify.verify_study(sy, ws_root=ws)
    direct_dicts = [f.to_dict() for f in direct]

    assert endpoint_body["findings"] == direct_dicts
    assert endpoint_body["summary"] == {
        "error": sum(1 for f in direct if f.level == "error"),
        "warning": sum(1 for f in direct if f.level == "warning"),
        "info": sum(1 for f in direct if f.level == "info"),
    }

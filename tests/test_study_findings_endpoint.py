"""Tests for ``POST /api/study-findings``
(``lib.study_findings_views.study_findings_draft``).

Phase 2.1 (rewire-first): this endpoint wraps
``vivarium_workbench.lib.study_findings.run_findings_walk`` unchanged — the plugin
still walks the study's outcomes and DRAFTS new ``findings[]`` entries, only the
caller (the workbench, on behalf of the ``/viva-study findings`` skill) moves.
These tests exercise the lib builder directly (the same "endpoint test calls the
lib fn" idiom as ``test_study_findings_populate_endpoint.py``) plus an
equivalence check against calling ``run_findings_walk`` directly.

NOTE — distinct from ``test_study_findings_populate_endpoint.py``, which covers
``finding_observations.populate_finding_observations`` (FILLS slots on EXISTING
findings). This one DRAFTS NEW findings from outcomes.
"""
from pathlib import Path

import pytest

from vivarium_workbench.lib import study_findings_views as views

# A study with one canonical run whose ``outcomes`` carry a PASS behavior-test
# result (``extract_outcomes`` reads ``runs[].outcomes`` — the dict shape here)
# and NO ``findings[]`` yet, so the outcome is uncovered → exactly one finding
# gets drafted. ``computed_outcomes`` is also present (realistic study.yaml
# shape) but the walk drafts off ``outcomes``.
STUDY_YAML_TEXT = """\
# A hand-authored study; a findings walk should DRAFT one new finding.
name: dnaa-test
objective: |
  Multi-line objective prose.
behavior_tests:
  - name: dnaa_atp_frac
    description: DnaA-ATP fraction stays within the calibrated band
    measure:
      path: listeners.dnaa_atp_fraction
    pass_if:
      low: 0.2
      high: 0.5
runs:
  - name: baseline-001
    canonical: true
    status: complete
    computed_outcomes:
      dnaa_atp_frac:
        measured_value: 0.35
    outcomes:
      dnaa_atp_frac:
        result: pass
        observed: 0.35
# trailing comment
"""


def _study_ws(tmp_path: Path, slug: str = "dnaa-test") -> "tuple[Path, Path]":
    ws = tmp_path / "ws"
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: findings-draft-test\n")
    (ws / ".pbg").mkdir()
    sy = sd / "study.yaml"
    sy.write_text(STUDY_YAML_TEXT)
    return ws, sy


def test_missing_study_400(tmp_path):
    ws, _ = _study_ws(tmp_path)
    body, status = views.study_findings_draft(ws, {})
    assert status == 400
    assert "study" in body["error"]


def test_unknown_study_404(tmp_path):
    ws, _ = _study_ws(tmp_path)
    body, status = views.study_findings_draft(ws, {"study": "does-not-exist"})
    assert status == 404
    assert "does-not-exist" in body["error"]


def test_draft_writes_new_findings(tmp_path):
    ws, sy = _study_ws(tmp_path)
    original = sy.read_text()

    body, status = views.study_findings_draft(ws, {"study": "dnaa-test"})

    assert status == 200
    assert body["study"] == "dnaa-test"
    # A finding was drafted from the uncovered outcome and written.
    assert body["proposed"] > 0
    assert body["appended"] == body["proposed"]
    assert body["dry_run"] is False
    assert body["wrote"] is True

    text = sy.read_text()
    assert text != original
    assert "findings:" in text  # the walk appended a findings[] block


def test_dry_run_does_not_write(tmp_path):
    ws, sy = _study_ws(tmp_path)
    original = sy.read_text()

    body, status = views.study_findings_draft(
        ws, {"study": "dnaa-test", "dry_run": True}
    )

    assert status == 200
    assert body["proposed"] > 0  # still proposes the same drafts
    assert body["dry_run"] is True
    assert body["wrote"] is False
    assert body["wrote_path"] is None
    assert sy.read_text() == original  # dry-run must not touch study.yaml


def test_equivalence_with_direct_walk_call(tmp_path):
    """The endpoint's proposed/skipped counts must match calling
    ``vivarium_workbench.lib.study_findings.run_findings_walk`` directly."""
    sf = pytest.importorskip("vivarium_workbench.lib.study_findings")

    ws, _ = _study_ws(tmp_path)
    endpoint_body, status = views.study_findings_draft(
        ws, {"study": "dnaa-test", "dry_run": True}
    )
    assert status == 200

    # Fresh copy for the direct call (dry-run, so neither call writes).
    _ws2, sy2 = _study_ws(tmp_path / "cmp2", slug="dnaa-test")
    direct = sf.run_findings_walk(sy2.parent, dry_run=True, out=lambda _m: None)

    assert endpoint_body["proposed"] == len(direct.proposed)
    assert endpoint_body["skipped_existing"] == len(direct.skipped_existing)

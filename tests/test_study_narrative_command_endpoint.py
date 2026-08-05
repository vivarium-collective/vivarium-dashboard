"""Tests for ``POST /api/study-narrative-command``
(``lib.study_narrative_command_views.study_narrative_command``).

Rewire-first: this endpoint wraps ``vivarium_workbench.lib.study_narrative``'s four
narrative-spine subcommands unchanged — the plugin still mutates study.yaml,
only the caller (the workbench, on behalf of ``/viva-study``) moves. These
tests exercise the lib builder directly (the same "endpoint test calls the lib
fn" idiom as ``test_study_findings_populate_endpoint.py``) plus an equivalence
check against calling the plugin callable directly.
"""
from pathlib import Path

import pytest

from vivarium_workbench.lib import study_narrative_command_views as views

# A bare study — every narrative subcommand either creates its target block
# (set-verdicts) or appends to an absent list, so no seed content is needed.
STUDY_YAML_TEXT = """\
# Hand-authored study; comments MUST survive the ruamel round-trip.
name: narr-test
objective: |
  Multi-line objective prose.
# trailing comment
"""


def _study_ws(tmp_path: Path, slug: str = "narr-test") -> tuple[Path, Path]:
    ws = tmp_path / "ws"
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: narrative-command-test\n")
    (ws / ".pbg").mkdir()
    sy = sd / "study.yaml"
    sy.write_text(STUDY_YAML_TEXT)
    return ws, sy


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_missing_study_400(tmp_path):
    ws, _ = _study_ws(tmp_path)
    body, status = views.study_narrative_command(
        ws, {"subcommand": "add-pivot", "args": {"id": "p1", "question": "q?"}}
    )
    assert status == 400
    assert "study" in body["error"]


def test_missing_subcommand_400(tmp_path):
    ws, _ = _study_ws(tmp_path)
    body, status = views.study_narrative_command(ws, {"study": "narr-test"})
    assert status == 400
    assert "subcommand" in body["error"]
    # all four valid names are listed for the caller.
    for name in ("set-verdicts", "add-literature-anchor", "add-pivot", "add-requirement"):
        assert name in body["error"]


def test_bad_subcommand_400(tmp_path):
    ws, _ = _study_ws(tmp_path)
    body, status = views.study_narrative_command(
        ws, {"study": "narr-test", "subcommand": "delete-everything"}
    )
    assert status == 400
    assert "subcommand" in body["error"]


def test_unknown_study_404(tmp_path):
    ws, _ = _study_ws(tmp_path)
    body, status = views.study_narrative_command(
        ws,
        {
            "study": "does-not-exist",
            "subcommand": "add-pivot",
            "args": {"id": "p1", "question": "q?"},
        },
    )
    assert status == 404
    assert "does-not-exist" in body["error"]


def test_missing_required_args_400(tmp_path):
    """A subcommand whose required dataclass fields are absent → 400 listing
    the missing field names."""
    ws, _ = _study_ws(tmp_path)
    # add-literature-anchor requires expectation + model_observable.
    body, status = views.study_narrative_command(
        ws,
        {
            "study": "narr-test",
            "subcommand": "add-literature-anchor",
            "args": {"expectation": "cells divide"},  # model_observable absent
        },
    )
    assert status == 400
    assert "model_observable" in body["error"]


def test_set_verdicts_requires_a_track_400(tmp_path):
    ws, sy = _study_ws(tmp_path)
    original = sy.read_text()
    body, status = views.study_narrative_command(
        ws, {"study": "narr-test", "subcommand": "set-verdicts", "args": {}}
    )
    assert status == 400
    assert "regression" in body["error"]
    assert sy.read_text() == original  # untouched


# ---------------------------------------------------------------------------
# Happy paths — one per subcommand kind
# ---------------------------------------------------------------------------


def test_set_verdicts_happy(tmp_path):
    pytest.importorskip("vivarium_workbench.lib.study_narrative")
    ws, sy = _study_ws(tmp_path)
    original = sy.read_text()

    body, status = views.study_narrative_command(
        ws,
        {
            "study": "narr-test",
            "subcommand": "set-verdicts",
            "args": {
                "regression": {"result": "PASS", "basis": "all regression tests green"},
                "biological": {"result": "MIXED"},
            },
        },
    )
    assert status == 200
    assert body["study"] == "narr-test"
    assert body["subcommand"] == "set-verdicts"
    assert body["dry_run"] is False
    assert isinstance(body["message"], str) and body["message"]

    text = sy.read_text()
    assert text != original
    assert "conclusion_verdicts" in text
    assert "PASS" in text
    assert "narr-test" in text  # other top-level keys preserved


def test_add_literature_anchor_happy(tmp_path):
    pytest.importorskip("vivarium_workbench.lib.study_narrative")
    ws, sy = _study_ws(tmp_path)
    original = sy.read_text()

    body, status = views.study_narrative_command(
        ws,
        {
            "study": "narr-test",
            "subcommand": "add-literature-anchor",
            "args": {
                "expectation": "doubling time ~40 min in glucose",
                "model_observable": "listeners.mass.cell_mass",
                "source": "Neidhardt 1990",
                "cites": ["neidhardt1990"],
            },
        },
    )
    assert status == 200
    assert isinstance(body["message"], str) and body["message"]

    text = sy.read_text()
    assert text != original
    assert "literature_anchors" in text
    assert "doubling time" in text


def test_add_pivot_happy(tmp_path):
    pytest.importorskip("vivarium_workbench.lib.study_narrative")
    ws, sy = _study_ws(tmp_path)
    original = sy.read_text()

    body, status = views.study_narrative_command(
        ws,
        {
            "study": "narr-test",
            "subcommand": "add-pivot",
            "args": {
                "id": "PIVOT-1",
                "question": "Add locked species or patch stoichMatrix?",
                "alternatives": ["A. locked species", "B. patch stoichMatrix"],
            },
        },
    )
    assert status == 200
    assert isinstance(body["message"], str) and body["message"]

    text = sy.read_text()
    assert text != original
    assert "design_pivot_required" in text
    assert "PIVOT-1" in text


def test_add_requirement_happy(tmp_path):
    pytest.importorskip("vivarium_workbench.lib.study_narrative")
    ws, sy = _study_ws(tmp_path)
    original = sy.read_text()

    body, status = views.study_narrative_command(
        ws,
        {
            "study": "narr-test",
            "subcommand": "add-requirement",
            "args": {
                "id": "REQ-1",
                "title": "Wire ppGpp feedback into metabolism",
                "effort": "M",
                "steps": ["read spec", "patch process"],
            },
        },
    )
    assert status == 200
    assert isinstance(body["message"], str) and body["message"]

    text = sy.read_text()
    assert text != original
    assert "implementation_requirements" in text
    assert "REQ-1" in text


# ---------------------------------------------------------------------------
# Dry-run does not write
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write(tmp_path):
    pytest.importorskip("vivarium_workbench.lib.study_narrative")
    ws, sy = _study_ws(tmp_path)
    original = sy.read_text()

    body, status = views.study_narrative_command(
        ws,
        {
            "study": "narr-test",
            "subcommand": "add-pivot",
            "args": {"id": "PIVOT-DRY", "question": "should this write?"},
            "dry_run": True,
        },
    )
    assert status == 200
    assert body["dry_run"] is True
    assert isinstance(body["message"], str) and body["message"]
    # file on disk is untouched.
    assert sy.read_text() == original


# ---------------------------------------------------------------------------
# Equivalence with a direct plugin call
# ---------------------------------------------------------------------------


def test_equivalence_with_direct_add_pivot(tmp_path):
    """The endpoint's write must match calling ``study_narrative.add_pivot``
    directly — same resulting study.yaml + same message string."""
    sn = pytest.importorskip("vivarium_workbench.lib.study_narrative")

    ws, sy = _study_ws(tmp_path)
    endpoint_body, status = views.study_narrative_command(
        ws,
        {
            "study": "narr-test",
            "subcommand": "add-pivot",
            "args": {"id": "PIVOT-EQ", "question": "equal?"},
        },
    )
    assert status == 200
    endpoint_text = sy.read_text()

    ws2, sy2 = _study_ws(tmp_path / "cmp2", slug="narr-test")
    _, direct_msg = sn.add_pivot(
        ws2, "narr-test", sn.DesignPivot(id="PIVOT-EQ", question="equal?")
    )

    assert endpoint_body["message"] == direct_msg
    assert endpoint_text == sy2.read_text()

"""Tests for ``POST /api/feedback-record-action``
(``lib.feedback_record_views.feedback_record_action``).

Rewire-first: this endpoint wraps
``viva_superpowers.feedback_actions.record_feedback_action`` unchanged — the
plugin still persists the tracked ``actions[item_id]`` entry into the feedback
yaml; only the caller (the workbench, on behalf of the feedback-respond skill)
moves off a direct plugin import. These tests exercise the lib builder directly
(same "endpoint test calls the lib fn" idiom as the sibling feedback/readout
endpoint tests) plus an equivalence check against calling
``record_feedback_action`` directly.
"""
from pathlib import Path

import pytest

from vivarium_workbench.lib import feedback_record_views as views

# A feedback yaml as written into investigations/<inv>/feedback/<ts>.yaml by the
# inline-feedback import: a ``study-<slug>`` annotation section with one entry.
# ``record_feedback_action`` locates this file by recomputing feedback_item_id
# over each annotation entry (section + ts + author), so no study.yaml is needed.
_INV = "dnaa"
_SLUG = "dnaa-test"
_SECTION = "study-" + _SLUG
_TS = "2026-01-01T00:00:00Z"
_AUTHOR = "expert"

FEEDBACK_YAML_TEXT = f"""\
meta:
  report_id: r-001
annotations:
  {_SECTION}:
    - ts: "{_TS}"
      author: {_AUTHOR}
      text: "Consider a follow-up on the ATP fraction."
"""


def _fb_ws(tmp_path: Path) -> "tuple[Path, str]":
    """Build a workspace with one imported feedback file; return (ws, item_id)."""
    from viva_superpowers.feedback_actions import feedback_item_id

    ws = tmp_path / "ws"
    fb_dir = ws / "investigations" / _INV / "feedback"
    fb_dir.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: feedback-record-test\n")
    (ws / ".pbg").mkdir()
    (fb_dir / "2026-01-01.yaml").write_text(FEEDBACK_YAML_TEXT)
    item_id = feedback_item_id(_SECTION, _TS, _AUTHOR)
    return ws, item_id


def test_missing_item_id_400(tmp_path):
    body, status = views.feedback_record_action(
        tmp_path / "ws", {"kind": "finding", "target_study": _SLUG, "proposed_text": "x"}
    )
    assert status == 400
    assert "item_id" in body["error"]


def test_missing_proposed_text_400(tmp_path):
    body, status = views.feedback_record_action(
        tmp_path / "ws", {"item_id": "fb-abc", "kind": "finding", "target_study": _SLUG}
    )
    assert status == 400
    assert "proposed_text" in body["error"]


def test_unknown_item_id_404(tmp_path):
    pytest.importorskip("viva_superpowers.feedback_actions")
    ws, _ = _fb_ws(tmp_path)
    body, status = views.feedback_record_action(
        ws,
        {
            "item_id": "fb-doesnotexist",
            "kind": "finding",
            "target_study": _SLUG,
            "proposed_text": "New finding about X.",
        },
    )
    assert status == 404
    assert body["recorded"] is False
    assert "fb-doesnotexist" in body["error"]


def test_record_persists_action(tmp_path):
    pytest.importorskip("viva_superpowers.feedback_actions")
    from viva_superpowers.feedback_actions import study_feedback_actions

    ws, item_id = _fb_ws(tmp_path)

    body, status = views.feedback_record_action(
        ws,
        {
            "item_id": item_id,
            "kind": "finding",
            "target_study": _SLUG,
            "proposed_text": "Draft a follow-up finding on ATP fraction.",
        },
    )

    assert status == 200
    assert body["recorded"] is True
    assert body["kind"] == "finding"
    assert Path(body["path"]).is_file()

    # Re-read via the pure aggregator: the action now persists on the item.
    agg = study_feedback_actions(ws, _SLUG)
    match = [it for it in agg["items"] if it["item_id"] == item_id]
    assert len(match) == 1
    action = match[0]["action"]
    assert action is not None
    assert action["kind"] == "finding"
    assert action["target_study"] == _SLUG
    assert action["proposed_text"] == "Draft a follow-up finding on ATP fraction."
    # A freshly recorded action derives status "open" (not yet applied).
    assert match[0]["status"] == "open"


def test_equivalence_with_direct_record_call(tmp_path):
    """The endpoint's result must match calling
    ``viva_superpowers.feedback_actions.record_feedback_action`` directly —
    same ``recorded``/``kind`` outcome on an equivalent workspace."""
    pbg_feedback_actions = pytest.importorskip("viva_superpowers.feedback_actions")

    ws, item_id = _fb_ws(tmp_path)
    endpoint_body, status = views.feedback_record_action(
        ws,
        {
            "item_id": item_id,
            "kind": "finding",
            "target_study": _SLUG,
            "proposed_text": "Draft a follow-up finding on ATP fraction.",
        },
    )
    assert status == 200

    # Fresh, equivalent workspace for the direct call.
    ws2, item_id2 = _fb_ws(tmp_path / "cmp2")
    assert item_id2 == item_id  # item_id is content-derived, so identical
    direct = pbg_feedback_actions.record_feedback_action(
        ws2,
        item_id2,
        kind="finding",
        target_study=_SLUG,
        proposed_text="Draft a follow-up finding on ATP fraction.",
    )

    assert endpoint_body["recorded"] == direct["recorded"] is True
    assert endpoint_body["kind"] == direct["kind"]

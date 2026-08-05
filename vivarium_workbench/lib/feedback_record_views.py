"""``POST /api/feedback-record-action`` builder — wraps
``viva_superpowers.feedback_actions.record_feedback_action``.

Rewire-first (same pattern as ``/api/feedback-apply-action`` and
``/api/study-readout-migrate``): the workbench keeps importing the plugin's
compute to BACK this endpoint so the responder skill can call the dashboard API
instead of importing ``viva_superpowers.feedback_actions`` directly.

``record_feedback_action`` is the SP3b *sibling* of ``apply_feedback_action``:
where apply EFFECTS a tracked action, record merely PERSISTS one. It writes an
``actions[item_id]`` entry (``status: open``) into the feedback yaml that
carries the matching annotation — located under
``investigations/<inv>/feedback/...`` by recomputing ``feedback_item_id`` over
each annotation entry. It therefore keys off ``item_id`` (NOT a study slug):
``ws_root`` is the workspace root, and no ``study.yaml`` needs to exist. It is a
best-effort primitive — a bad ``kind`` or an unknown ``item_id`` come back as
``{"recorded": False, "error": ...}`` rather than raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# Fields consumed as named args of ``record_feedback_action``; anything else in
# the body is forwarded to its ``**extra`` (which persists non-None values).
_KNOWN = {"item_id", "kind", "target_study", "proposed_text", "target_finding", "by"}


def feedback_record_action(ws_root: Path, body: dict) -> "tuple[dict, int]":
    """POST /api/feedback-record-action: persist a tracked feedback action.

    Body (from ``record_feedback_action``'s signature)::

        {item_id, kind, target_study, proposed_text,
         target_finding?, by?, ...extra}

    The four required keys map to the primitive's required positional/keyword
    args; ``target_finding``/``by`` are optional; any additional keys are
    forwarded to its ``**extra`` (non-None values are persisted onto the
    action). Keys off ``item_id`` — NO study slug is resolved and no
    ``study.yaml`` need exist.

    Returns ``(result, 200)`` where ``result`` is exactly what
    ``record_feedback_action`` returns — ``{recorded: True, path, kind}``.

    - 400 ``{"error": "<field> required"}`` — missing/blank required field.
    - 400 ``{recorded: False, error: "unknown kind ..."}`` — the primitive
      rejected the ``kind`` (not one of its valid kinds).
    - 404 ``{recorded: False, error: "no annotation matches item_id ..."}`` —
      no feedback annotation resolves to ``item_id``.
    - 500 ``{"error": "feedback-record requires pbg-superpowers: <e>"}`` — the
      plugin (or its ``feedback_actions`` module) isn't installed.
    - 500 ``{"error": "record failed: <e>"}`` — any other failure raised while
      recording.
    """
    body = body or {}

    item_id = body.get("item_id")
    if not item_id or not str(item_id).strip():
        return {"error": "item_id required"}, 400
    kind = body.get("kind")
    if not kind or not str(kind).strip():
        return {"error": "kind required"}, 400
    target_study = body.get("target_study")
    if not target_study or not str(target_study).strip():
        return {"error": "target_study required"}, 400
    proposed_text = body.get("proposed_text")
    if proposed_text is None or not str(proposed_text).strip():
        return {"error": "proposed_text required"}, 400

    try:
        from viva_superpowers.feedback_actions import record_feedback_action
    except ImportError as e:  # noqa: BLE001
        return {"error": f"feedback-record requires pbg-superpowers: {e}"}, 500

    target_finding = body.get("target_finding")
    by = body.get("by")
    extra: dict[str, Any] = {k: v for k, v in body.items() if k not in _KNOWN}

    try:
        result = record_feedback_action(
            Path(ws_root),
            str(item_id).strip(),
            kind=str(kind).strip(),
            target_study=str(target_study).strip(),
            proposed_text=str(proposed_text),
            target_finding=str(target_finding).strip() if target_finding else None,
            by=str(by).strip() if by else None,
            **extra,
        )
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:  # noqa: BLE001 — never a bare 500 with no message
        return {"error": f"record failed: {e}"}, 500

    # record_feedback_action is best-effort: an unknown item_id or a bad kind
    # comes back as {"recorded": False, "error": ...} without raising.
    if not result.get("recorded"):
        err = str(result.get("error") or "")
        if "no annotation matches" in err:
            return result, 404
        return result, 400
    return result, 200

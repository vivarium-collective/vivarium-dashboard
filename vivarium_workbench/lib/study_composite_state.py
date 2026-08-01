"""Lower a single study to its composite bigraph state for the embedded loom.

A study (``study.yaml`` / legacy ``spec.yaml``) declares an execution interface
— a composite-generator id plus config (see ``study_spec.study_interface``). This
module resolves a study SLUG to that ``{composite, config}`` and reuses
``composite_state_views.build_composite_state`` (the warm-worker
``build_generator`` path) so the returned ``{state, kind, ...}`` envelope is
byte-for-byte the same shape ``/api/composite-state`` returns.

The embedded ``bigraph-loom`` is purely state-driven: point its ``?stateUrl=`` at
this endpoint and it renders the study's subcomposites, emitter, visualizations,
and report-card steps with zero loom changes — exactly as it does for a plain
composite card under Modules.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import yaml

from vivarium_workbench.lib import composite_state_views as _views
from vivarium_workbench.lib.study_spec import study_interface, study_spec_path


def build_study_composite_state(
    ws_root: Path | str, study_slug: str, *, fresh: bool = False
) -> Tuple[dict, int]:
    """``(payload, status)`` — the study's lowered composite state, or an error.

    Resolves ``study_slug`` -> ``{composite, config}`` via ``study_interface``,
    then lowers that composite id (with the study's params as ``overrides``)
    through ``build_composite_state``. Returns the same ``{state, kind, ...}``
    envelope, annotated with ``study`` + ``composite_ref`` so the caller can
    label the card. Error bodies mirror ``build_composite_state``'s
    ``{error, ...}`` shape with the matching status code.
    """
    ws_root = Path(ws_root)
    slug = (study_slug or "").strip()
    if not slug:
        return {"error": "study slug required"}, 400

    spec_path = study_spec_path(ws_root, slug)
    if not spec_path.is_file():
        return {"error": f"study not found: {slug}", "unresolved": True, "ref": slug}, 404
    try:
        spec = yaml.safe_load(spec_path.read_text()) or {}
    except Exception as e:  # noqa: BLE001 — surface unreadable specs, don't crash
        return {"error": f"study spec unreadable: {e}"}, 500

    try:
        iface = study_interface(spec)
    except Exception as e:  # noqa: BLE001 — malformed interface → 400, not 500
        return {"error": f"study interface invalid: {e}"}, 400

    composite_ref = iface.get("composite") or slug
    overrides = iface.get("config") or None

    body, status = _views.build_composite_state(
        ws_root, composite_ref, fresh=fresh, overrides=overrides
    )
    if status == 200 and isinstance(body, dict):
        body.setdefault("study", slug)
        body.setdefault("composite_ref", composite_ref)
    return body, status

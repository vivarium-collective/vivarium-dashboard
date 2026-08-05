"""``POST /api/study-narrative-command`` builder — wraps
``viva_superpowers.study_narrative``'s four narrative-spine subcommands.

Rewire-first: the workbench keeps importing the plugin's compute to BACK this
endpoint (no module move yet). This lets the ``/viva-study`` skill stop
importing ``viva_superpowers.study_narrative`` directly and call the dashboard
API instead, matching the rewire-first pattern already used by
``/api/study-readout-migrate`` and ``/api/study-findings-populate-observations``.

``study_narrative`` exposes four public callables that each mutate one v4
narrative-spine field on ``studies/<slug>/study.yaml`` and return
``(spec, diff_or_message_string)``:

- ``set-verdicts``          → ``set_verdicts``          (conclusion_verdicts)
- ``add-literature-anchor`` → ``add_literature_anchor`` (literature_anchors[])
- ``add-pivot``             → ``add_pivot``             (design_pivot_required[])
- ``add-requirement``       → ``add_requirement``       (implementation_requirements[])

Every callable takes the WORKSPACE ROOT + the study ``slug`` and resolves the
study dir itself; ``dry_run=True`` computes the proposed diff without writing.
"""

from __future__ import annotations

from dataclasses import MISSING, fields
from pathlib import Path
from typing import Optional

from vivarium_workbench.lib.study_spec import study_dir as resolve_study_dir
from vivarium_workbench.lib.study_spec import study_spec_file

_SUBCOMMANDS = (
    "set-verdicts",
    "add-literature-anchor",
    "add-pivot",
    "add-requirement",
)


def _blank(v) -> bool:
    """A value counts as absent if it is None or a whitespace-only string."""
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _required_fields(dc) -> "list[str]":
    """Names of dataclass fields with no default and no default_factory."""
    return [
        f.name
        for f in fields(dc)
        if f.default is MISSING and f.default_factory is MISSING
    ]


def _valid_fields(dc) -> "set[str]":
    return {f.name for f in fields(dc)}


def study_narrative_command(ws_root: Path, body: dict) -> "tuple[dict, int]":
    """POST /api/study-narrative-command: mutate a v4 narrative-spine field.

    Body::

        {study: <slug>, subcommand: <one-of-four>, args: {...}, dry_run?: bool}

    ``args`` carries the chosen subcommand's fields, keyed by the corresponding
    dataclass field name:

    - ``set-verdicts``: ``args`` is a dict of up to three tracks —
      ``{regression?, biological?, explanatory?}`` — each a
      ``{result?, basis?}`` dict (→ ``VerdictUpdate``). At least one track
      required.
    - ``add-literature-anchor``: ``{expectation, model_observable, source?,
      status_in_workspace?, cites?}`` (→ ``LiteratureAnchor``).
    - ``add-pivot``: ``{id, question, alternatives?, status?,
      requested_response?, notes?}`` (→ ``DesignPivot``).
    - ``add-requirement``: ``{id, title, kind?, effort?, status?, description?,
      steps?, unblocks?, defer_until?}`` (→ ``ImplementationRequirement``).

    On success returns ``({study, subcommand, message, dry_run}, 200)`` where
    ``message`` is the diff/summary string the plugin callable returns.

    - 400 ``{"error": "study slug required"}`` — missing/blank ``study``.
    - 400 ``{"error": "subcommand required; one of: ..."}`` — missing/unknown
      ``subcommand``.
    - 400 ``{"error": "<subcommand> requires args: ..."}`` — required args for
      the chosen subcommand are absent.
    - 404 ``{"error": "study not found: <slug>"}`` — no ``study.yaml`` for slug.
    - 500 ``{"error": "study narrative command requires viva_superpowers: ..."}``
      — the plugin isn't installed.
    - 500 ``{"error": "study narrative command failed: ..."}`` — any other
      failure (e.g. a plugin ``ValueError`` on invalid verdict/duplicate id).
    """
    body = body or {}

    slug: Optional[str] = body.get("study")
    if _blank(slug):
        return {"error": "study slug required"}, 400
    slug = str(slug).strip()

    subcommand: Optional[str] = body.get("subcommand")
    if _blank(subcommand) or subcommand not in _SUBCOMMANDS:
        return {
            "error": (
                f"subcommand required; one of: {', '.join(_SUBCOMMANDS)}"
            )
        }, 400

    args = body.get("args") or {}
    if not isinstance(args, dict):
        return {"error": "args must be an object"}, 400

    dry_run = bool(body.get("dry_run", False))

    # 404-guard by resolving the study dir ourselves (the plugin fns resolve it
    # too, but from the workspace root + slug — we still want a clean 404).
    ws_path = Path(ws_root)
    sdir = resolve_study_dir(ws_path, slug)
    if not study_spec_file(sdir).is_file():
        return {"error": f"study not found: {slug}"}, 404

    try:
        from viva_superpowers.study_narrative import (
            DesignPivot,
            ImplementationRequirement,
            LiteratureAnchor,
            VerdictUpdate,
            add_literature_anchor,
            add_pivot,
            add_requirement,
            set_verdicts,
        )
    except ImportError as e:  # noqa: BLE001
        return {
            "error": f"study narrative command requires viva_superpowers: {e}"
        }, 500

    try:
        if subcommand == "set-verdicts":
            tracks = {}
            for key in ("regression", "biological", "explanatory"):
                td = args.get(key)
                if td:
                    if not isinstance(td, dict):
                        return {
                            "error": f"set-verdicts: '{key}' must be an object"
                        }, 400
                    tracks[key] = VerdictUpdate(
                        result=td.get("result"),
                        basis=td.get("basis"),
                    )
            if not tracks:
                return {
                    "error": (
                        "set-verdicts requires args: at least one of "
                        "regression, biological, explanatory"
                    )
                }, 400
            _, message = set_verdicts(
                ws_path,
                slug,
                regression=tracks.get("regression"),
                biological=tracks.get("biological"),
                explanatory=tracks.get("explanatory"),
                dry_run=dry_run,
            )

        else:
            dc_map = {
                "add-literature-anchor": (LiteratureAnchor, add_literature_anchor),
                "add-pivot": (DesignPivot, add_pivot),
                "add-requirement": (ImplementationRequirement, add_requirement),
            }
            dc_cls, fn = dc_map[subcommand]

            required = _required_fields(dc_cls)
            missing = [r for r in required if _blank(args.get(r))]
            if missing:
                return {
                    "error": (
                        f"{subcommand} requires args: {', '.join(missing)}"
                    )
                }, 400

            valid = _valid_fields(dc_cls)
            kwargs = {k: v for k, v in args.items() if k in valid}
            payload = dc_cls(**kwargs)
            _, message = fn(ws_path, slug, payload, dry_run=dry_run)

    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:  # noqa: BLE001 — never a bare 500 with no message
        return {"error": f"study narrative command failed: {e}"}, 500

    return {
        "study": slug,
        "subcommand": subcommand,
        "message": message,
        "dry_run": dry_run,
    }, 200

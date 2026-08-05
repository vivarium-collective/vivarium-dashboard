"""``POST /api/study-findings`` builder — wraps
``vivarium_workbench.lib.study_findings.run_findings_walk``.

Phase 2.1 (rewire-first): the workbench keeps importing the plugin's compute to
BACK this endpoint (no module move yet). This lets
``skills/viva-study/SKILL.md`` (the ``/viva-study findings`` subcommand) stop
importing ``vivarium_workbench.lib.study_findings`` directly and call the dashboard
API instead, matching the rewire-first pattern already used by
``/api/study-readout-migrate`` and ``/api/study-findings-populate-observations``.

``run_findings_walk(study_dir, *, auto=False, dry_run=False)`` walks every
``behavior_tests[]`` outcome under ``runs[]`` (see
``study_findings.extract_outcomes`` — it reads ``runs[].outcomes`` /
``runs[].test_results``) and DRAFTS one ``findings[]`` entry per outcome not
already covered by an ``evidence.from_test`` link, then atomically appends the
drafts to ``study.yaml``. ``dry_run=True`` computes the proposed drafts without
writing. It returns a :class:`~vivarium_workbench.lib.study_findings.WalkResult`
dataclass; this builder flattens it to a JSON-able summary dict of counts.

NOTE — distinct from ``/api/study-findings-populate-observations``
(``finding_observations.populate_finding_observations``), which FILLS code-owned
slots on findings that ALREADY exist. This endpoint DRAFTS new ``findings[]``
from outcomes. The two are complementary, not interchangeable.

The endpoint does ONLY the deterministic draft/write (no ``prompter`` is
supplied, so ``run_findings_walk`` appends every draft as-is regardless of
``auto``) — the interactive curation of the drafts stays agent-side.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from vivarium_workbench.lib.study_spec import study_dir as resolve_study_dir
from vivarium_workbench.lib.study_spec import study_spec_file


def study_findings_draft(ws_root: Path, body: dict) -> "tuple[dict, int]":
    """POST /api/study-findings: draft new findings from a study's outcomes.

    Body: ``{study: <slug>, auto?: bool, dry_run?: bool}`` — ``auto`` and
    ``dry_run`` map to ``run_findings_walk``'s keywords of the same name; both
    default to ``False``. With no ``prompter`` the walk writes every draft, so
    ``auto`` is effectively always-on for this endpoint; it is still forwarded
    for signature fidelity.

    Returns ``(summary, 200)`` on success, where ``summary`` flattens the
    plugin's ``WalkResult`` to counts — ``proposed`` / ``appended`` /
    ``skipped_existing`` (ints), ``cited_bib_keys`` / ``unknown_bib_keys``
    (sorted lists), ``dry_run`` / ``wrote`` (bools), ``wrote_path`` (str|None)
    — plus the resolved ``study`` slug.

    - 400 ``{"error": "study slug required"}`` — missing/blank ``study``.
    - 404 ``{"error": "study not found: <slug>"}`` — no ``study.yaml``/
      ``spec.yaml`` for the slug.
    - 500 ``{"error": "findings draft requires viva_superpowers: <e>"}`` — the
      plugin (or its ``study_findings`` module) isn't installed.
    - 500 ``{"error": "findings draft failed: <e>"}`` — any other failure
      raised while drafting/writing the findings.
    """
    slug: Optional[str] = (body or {}).get("study")
    if not slug or not str(slug).strip():
        return {"error": "study slug required"}, 400
    slug = str(slug).strip()

    auto = bool((body or {}).get("auto") or False)
    dry_run = bool((body or {}).get("dry_run") or False)

    sdir = resolve_study_dir(Path(ws_root), slug)
    if not study_spec_file(sdir).is_file():
        return {"error": f"study not found: {slug}"}, 404

    try:
        from vivarium_workbench.lib.study_findings import run_findings_walk
    except ImportError as e:  # noqa: BLE001
        return {"error": f"findings draft requires viva_superpowers: {e}"}, 500

    try:
        # Silence the walk's human-readable progress chatter (default ``print``
        # would go to the server's stdout); the summary is returned instead.
        walk = run_findings_walk(
            sdir, auto=auto, dry_run=dry_run, out=lambda _msg: None
        )
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:  # noqa: BLE001 — never a bare 500 with no message
        return {"error": f"findings draft failed: {e}"}, 500

    summary = {
        "study": slug,
        "proposed": len(walk.proposed),
        "appended": len(walk.appended),
        "skipped_existing": len(walk.skipped_existing),
        "cited_bib_keys": sorted(walk.cited_bib_keys),
        "unknown_bib_keys": sorted(walk.unknown_bib_keys),
        "dry_run": bool(walk.dry_run),
        "wrote": walk.wrote_path is not None,
        "wrote_path": str(walk.wrote_path) if walk.wrote_path else None,
    }
    return summary, 200

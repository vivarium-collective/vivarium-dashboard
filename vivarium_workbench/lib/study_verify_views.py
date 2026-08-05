"""``POST /api/study-verify`` builder — wraps
``vivarium_workbench.lib.study_verify.verify_study``.

Rewire-first (mirrors ``/api/study-readout-migrate`` and
``/api/study-findings-populate-observations``): the workbench keeps importing
the plugin's compute to BACK this endpoint (no module move). This lets the
``/viva-study verify`` skill stop shelling out to
``python -m vivarium_workbench.lib.study_verify`` and call the dashboard API instead.

``verify_study(study_yaml, ws_root=None)`` is a pure, static cross-reference
verifier: it parses a ``study.yaml`` and returns a flat ``list[VerifyFinding]``
(baseline/variant/simulation-set/behavior-test/observable/parent-study/cite/
finding-evidence consistency). It never runs a simulation. ``ws_root`` enables
workspace-level cross-checks (parent studies, bibtex keys); we always pass it.

The response mirrors the plugin CLI's ``--json`` shape
(``{study_yaml, findings, summary}``) — ``findings`` serialized via each
``VerifyFinding.to_dict()`` and ``summary`` the same ``{error, warning, info}``
level counts — plus the resolved ``study`` slug.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from vivarium_workbench.lib.study_spec import study_dir as resolve_study_dir
from vivarium_workbench.lib.study_spec import study_spec_file


def study_verify(ws_root: Path, body: dict) -> "tuple[dict, int]":
    """POST /api/study-verify: statically verify a study.yaml's cross-references.

    Body: ``{study: <slug>}``.

    Returns ``(result, 200)`` on success, where ``result`` matches the plugin
    CLI's ``--json`` output plus the resolved slug —
    ``{study, study_yaml, findings: [...], summary: {error, warning, info}}``.
    ``findings`` are ``VerifyFinding.to_dict()`` mappings
    (``{level, check, field_path, message}``). No simulation is executed.

    - 400 ``{"error": "study slug required"}`` — missing/blank ``study``.
    - 404 ``{"error": "study not found: <slug>"}`` — no ``study.yaml``/
      ``spec.yaml`` for the slug.
    - 500 ``{"error": "study verify requires viva_superpowers: <e>"}`` — the
      plugin (or its ``study_verify`` module) isn't installed.
    - 500 ``{"error": "study verify failed: <e>"}`` — any other failure raised
      while verifying.
    """
    slug: Optional[str] = (body or {}).get("study")
    if not slug or not str(slug).strip():
        return {"error": "study slug required"}, 400
    slug = str(slug).strip()

    sdir = resolve_study_dir(Path(ws_root), slug)
    spec = study_spec_file(sdir)
    if not spec.is_file():
        return {"error": f"study not found: {slug}"}, 404

    try:
        from vivarium_workbench.lib.study_verify import verify_study
    except ImportError as e:  # noqa: BLE001
        return {"error": f"study verify requires viva_superpowers: {e}"}, 500

    try:
        findings = verify_study(spec, ws_root=Path(ws_root))
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:  # noqa: BLE001 — never a bare 500 with no message
        return {"error": f"study verify failed: {e}"}, 500

    finding_dicts = [f.to_dict() for f in findings]
    summary = {
        "error": sum(1 for f in findings if f.level == "error"),
        "warning": sum(1 for f in findings if f.level == "warning"),
        "info": sum(1 for f in findings if f.level == "info"),
    }
    return {
        "study": slug,
        "study_yaml": str(spec),
        "findings": finding_dicts,
        "summary": summary,
    }, 200

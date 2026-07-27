"""Read-only L0-L5 study-reproducibility audit view.

Wraps :func:`viva_superpowers.study_audit.audit_workspace` behind the same
``(body, status)`` contract used by :mod:`investigation_graph_views`, so the
``GET /api/audit`` route is a thin ``JSONResponse`` passthrough. This is the
*visible* companion to the CI reproducibility gate (which lives in v2ecoli CI);
it is purely informational — it runs no gate and applies no allowlist.

Tolerant by design: a workspace with no studies, an unimportable audit module,
or any ``audit_workspace`` error yields ``({"error": ..., "studies": [],
"investigations": []}, 200)`` — never a 500 — so the UI degrades gracefully.
"""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _workspace_packages(ws_root: Path) -> list[str]:
    """Best-effort import names for the workspace's own composite generators.

    The workspace Python package registers its ``@composite_generator``
    decorators only when imported, so include it and its ``.composites``
    subpackage as ``extra_packages`` — the same lever the CLI ``--package`` flag
    provides — so workspace-local composites resolve during the audit.
    """
    try:
        pkg = WorkspacePaths.load(ws_root).package.name
    except Exception:  # noqa: BLE001 — best-effort
        return []
    if not pkg:
        return []
    return [pkg, f"{pkg}.composites"]


def build_audit(ws_root) -> tuple[dict, int]:
    """Run the audit and return ``(report, 200)``.

    Two layers, each best-effort:
      - the L0-L5 **reproducibility grade** (:mod:`audit_grade`, self-contained —
        works with or without the upstream package), attached as ``grade`` on
        each study/investigation block + ``summary.grade_distribution``;
      - the upstream **structural** audit (``viva_superpowers.study_audit``),
        whose per-check levels/verdicts fill each block's ``checks`` when present.

    When ``study_audit`` is unavailable the report is built from the grade alone,
    so the Audit tab (and published snapshot) still show reproducibility scores.
    Tolerant: any failure -> a 200 with an ``error`` note, never a 500.
    """
    ws_root = Path(ws_root)

    try:
        from vivarium_workbench.lib.audit_grade import grade_workspace
        grades = grade_workspace(ws_root)
    except Exception as exc:  # noqa: BLE001 — grade is best-effort
        grades = {"studies": {}, "investigations": {}, "distribution": {}, "error": str(exc)}

    report = None
    err = grades.get("error") or ""
    try:
        from viva_superpowers import study_audit
        report = study_audit.audit_workspace(
            ws_root, extra_packages=_workspace_packages(ws_root) or None
        ).as_dict()
    except Exception as exc:  # noqa: BLE001 — dependency missing/broken: degrade, don't 500
        err = err or f"study_audit unavailable: {exc}"

    if report is None:
        report = {
            "error": err,
            "studies": [{"slug": s, "worst": "pass", "checks": []} for s in grades["studies"]],
            "investigations": [{"slug": s, "worst": "pass", "checks": []}
                               for s in grades["investigations"]],
            "summary": {"n_studies": len(grades["studies"]),
                        "n_investigations": len(grades["investigations"]),
                        "hard_failures": 0},
        }

    for blk in report.get("studies", []):
        g = grades["studies"].get(blk.get("slug"))
        if g:
            blk["grade"] = g
    for blk in report.get("investigations", []):
        g = grades["investigations"].get(blk.get("slug"))
        if g:
            blk["grade"] = g
    report.setdefault("summary", {})["grade_distribution"] = grades.get("distribution", {})
    return report, 200

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
    """Run the L0-L5 audit and return ``(report.as_dict(), 200)``.

    Derives the workspace's own package from :class:`WorkspacePaths` and passes
    it as ``extra_packages`` so its composites resolve. Tolerant: any failure ->
    ``({"error": str, "studies": [], "investigations": []}, 200)``.
    """
    ws_root = Path(ws_root)
    empty = {"error": "", "studies": [], "investigations": []}
    try:
        from viva_superpowers import study_audit
    except Exception as exc:  # noqa: BLE001 — dependency missing/broken: degrade, don't 500
        return {**empty, "error": f"study_audit unavailable: {exc}"}, 200

    extra_packages = _workspace_packages(ws_root)
    try:
        report = study_audit.audit_workspace(
            ws_root, extra_packages=extra_packages or None
        )
        return report.as_dict(), 200
    except Exception as exc:  # noqa: BLE001 — audit is best-effort; never fatal
        return {**empty, "error": f"audit failed: {exc}"}, 200

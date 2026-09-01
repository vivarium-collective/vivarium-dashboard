# vivarium_workbench/lib/analysis_tools_simularium.py
"""Discover studies that produced a Simularium trajectory (``*.simularium``),
so the Analysis-tab "Simularium Viewer" tool can offer them.

A trajectory is written by viva-simularium's ``SimulariumAnalysis`` into a
study's ``viz/`` tree during the Evaluate-stage flush. Mirrors
``analysis_tools_3d.studies_with_3d_pack``: pure filesystem scan, no registry.
"""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _served_url(ws_root: Path, f: Path) -> str:
    """Workspace-root-relative HTTP path — the catch-all static route serves any
    file under the workspace tree at ``/<path-relative-to-ws_root>``."""
    return "/" + str(f.relative_to(ws_root)).replace("\\", "/")


def studies_with_simularium(ws_root) -> list[dict]:
    """``[{study, trajectories: [{name, url}]}]`` for every study that has at
    least one ``*.simularium`` under its dir (excluding raw ``parquet-runs``
    internals). Newest trajectory first within a study."""
    ws_root = Path(ws_root)
    try:
        studies_dir = WorkspacePaths.load(ws_root).studies
    except Exception:  # noqa: BLE001
        studies_dir = ws_root / "studies"
    out: list[dict] = []
    if not studies_dir.is_dir():
        return out
    for study_dir in sorted(p for p in studies_dir.iterdir() if p.is_dir()):
        trajs = [t for t in study_dir.rglob("*.simularium")
                 if "parquet-runs" not in t.parts and t.is_file()]
        if not trajs:
            continue
        trajs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        files = [{"name": t.stem, "url": _served_url(ws_root, t)} for t in trajs]
        out.append({"study": study_dir.name, "trajectories": files})
    return out

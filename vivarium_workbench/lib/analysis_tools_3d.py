# vivarium_workbench/lib/analysis_tools_3d.py
"""3D-pack capability: which studies advertise ``3d_pack`` and their saved-view
gallery. A study advertises 3d_pack if it has viz/3d/*.pack.json on disk OR a
configured hosted pack in ui.viz_viewer_urls. Reuses the existing pack scan."""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib.saved_visualizations import build_saved_visualizations

_INITIAL_HINTS = ("initial", "birth", "10s", "t10", "start")


def _hosted_viewer_urls(ws_root) -> dict:
    """study -> hosted viewer/models URL from ui.viz_viewer_urls (best-effort).

    ``workspace_config.read_ui_config`` does not exist in this codebase; read
    ``workspace.yaml`` directly, mirroring ``saved_visualizations.py:109-115``.
    """
    try:
        ws = yaml.safe_load(
            (Path(ws_root) / "workspace.yaml").read_text(encoding="utf-8")
        ) or {}
    except Exception:  # noqa: BLE001
        return {}
    ui = ws.get("ui") or {}
    urls = ui.get("viz_viewer_urls") or {}
    return dict(urls) if isinstance(urls, dict) else {}


def _pack_name_rank(name: str) -> int:
    n = (name or "").lower()
    return 0 if any(h in n for h in _INITIAL_HINTS) else 1


def studies_with_3d_pack(ws_root) -> list[dict]:
    saved = (build_saved_visualizations(ws_root) or {}).get("saved") or []
    by_study: dict[str, list[dict]] = {}
    for entry in saved:
        study = entry.get("study")
        if not study:
            continue
        by_study.setdefault(study, []).append(
            {"name": entry.get("name") or "snapshot",
             "file": entry.get("pack_url")})
    hosted = _hosted_viewer_urls(ws_root)
    out = []
    studies = set(by_study) | set(hosted)
    for study in sorted(studies):
        packs = sorted(by_study.get(study, []),
                        key=lambda p: (_pack_name_rank(p["name"]), p["name"]))
        rec = {"study": study, "packs": packs}
        if hosted.get(study):
            rec["viewer_url"] = hosted[study]
        out.append(rec)
    return out


def study_models_manifest(ws_root, study) -> list[dict]:
    for s in studies_with_3d_pack(ws_root):
        if s["study"] == study:
            return sorted(s.get("packs", []),
                          key=lambda p: (_pack_name_rank(p["name"]), p["name"]))
    return []

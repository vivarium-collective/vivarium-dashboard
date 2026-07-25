# vivarium_workbench/lib/analysis_tools.py
"""Compose the Analysis Tools tab: external viewers + built-in tools, each
matched to the runs/studies whose capabilities satisfy the tool's ``requires``.
Match rule: set(requires) <= set(candidate.capabilities)."""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib.analysis_viewers import viewers_public
from vivarium_workbench.lib.simulations_index import build_simulations_data


def match(requires, candidates: list[dict]) -> list[dict]:
    req = set(requires or [])
    if not req:
        return []
    return [c for c in candidates if req <= set(c.get("capabilities") or [])]


def builtin_tools() -> list[dict]:
    return [
        {"id": "data-explorer", "title": "Data Explorer",
         "description": "Interactively explore a run: timeseries, scatter, "
                        "allocation, and flux maps.",
         "kind": "embed-explorer", "requires": ["observables"]},
        {"id": "parsimony-viewer", "title": "Parsimony Viewer",
         "description": "3D molecular packing of a cell — saved views at "
                        "declared times.",
         "kind": "embed-3d", "requires": ["3d_pack"]},
    ]


def _run_candidates(ws_root) -> list[dict]:
    data = build_simulations_data(ws_root) or {}
    out = []
    for r in data.get("simulations", []):
        out.append({"ref": r.get("run_id"),
                    "label": r.get("label") or r.get("sim_name") or r.get("run_id"),
                    "detail": r.get("emitter_type") or "",
                    "capabilities": r.get("capabilities") or []})
    return out


def _pack_candidates(ws_root) -> list[dict]:
    from vivarium_workbench.lib.analysis_tools_3d import studies_with_3d_pack
    out = []
    for s in studies_with_3d_pack(ws_root):
        views = ", ".join(p["name"] for p in s.get("packs", [])) or "3D pack"
        out.append({"ref": s["study"], "label": s["study"],
                    "detail": views, "capabilities": ["3d_pack"],
                    "viewer_url": s.get("viewer_url")})
    return out


def build_analysis_tools(ws_root) -> list[dict]:
    ws_root = Path(ws_root)
    runs = _run_candidates(ws_root)
    packs = _pack_candidates(ws_root)
    tools: list[dict] = []

    # external contributed viewers (may or may not declare requires)
    for v in viewers_public(ws_root):
        v = dict(v)
        v.setdefault("requires", [])
        v["matched"] = match(v["requires"], runs) if v["requires"] else []
        tools.append(v)

    # built-in tools
    for t in builtin_tools():
        t = dict(t)
        cands = packs if "3d_pack" in t["requires"] else runs
        t["matched"] = match(t["requires"], cands)
        t["unmatched_reason"] = (
            f"No compatible runs — needs {', '.join(t['requires'])}."
            if not t["matched"] else "")
        tools.append(t)
    return tools

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


def _run_label(r: dict) -> str:
    """A concise, unique-enough label for a run's result dropdown. A run's stored
    ``label`` is a verbose composite-param dump (``cache_dir=…, config_overrides=
    {}, …``) — unusable in a picker — so prefer the run_id with any dotted module
    prefix stripped (``v2ecoli.composites.baseline__…__b026df`` -> ``baseline__…__
    b026df``), which keeps the disambiguating hash. Falls back to sim_name."""
    rid = str(r.get("run_id") or "")
    short = rid.rsplit(".", 1)[-1] if rid else ""
    return short or str(r.get("sim_name") or "") or rid or "run"


def _run_candidates(ws_root) -> list[dict]:
    data = build_simulations_data(ws_root) or {}
    out = []
    for r in data.get("simulations", []):
        out.append({"ref": r.get("run_id"),
                    "label": _run_label(r),
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

    pack_ids = {c["ref"] for c in packs}

    # external contributed viewers (may or may not declare requires). The
    # built-in Parsimony Viewer natively renders every 3D pack — it resolves the
    # hosted/bundled viewer itself and always opens — so a legacy contributed
    # viewer whose targets are ALL 3D-pack studies is a duplicate of it (and, in
    # practice, the fragile one: its launch goes through the env worker and can
    # 404). Drop such a viewer so there is exactly one, always-working 3D card.
    native_3d = bool(packs)
    for v in viewers_public(ws_root):
        v = dict(v)
        v.setdefault("requires", [])
        tgts = v.get("targets") or []
        if (native_3d and not v["requires"] and tgts
                and all(isinstance(t, dict) and t.get("study") in pack_ids
                        for t in tgts)):
            continue  # duplicate of the built-in Parsimony Viewer
        v["matched"] = match(v["requires"], runs) if v["requires"] else []
        tools.append(v)

    # Built-in tools are capability-matched: only surface one where THIS
    # workspace actually has data for it (an observables run for the Data
    # Explorer, a 3d_pack for the Parsimony Viewer). That keeps these
    # v2ecoli-flavored tools out of workspaces that will never satisfy them
    # (e.g. human-atlas shows only its own HRA Organ Viewer) instead of listing
    # permanently-empty "needs observables / needs 3d_pack" cards.
    for t in builtin_tools():
        t = dict(t)
        cands = packs if "3d_pack" in t["requires"] else runs
        t["matched"] = match(t["requires"], cands)
        if not t["matched"]:
            continue
        t["unmatched_reason"] = ""
        tools.append(t)
    return tools

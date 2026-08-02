"""Compile a workspace investigation into a **runnable** process-bigraph
composite — the execution substrate for "investigation as a composite".

Distinct from ``investigation_composite.py`` (which builds a pull-or-compute
*trigger document*): this module builds an executable ``Composite`` state dict
whose ``StudyStep``s run the member studies and whose ``InvestigationAnalysisStep``s
run investigation-level analyses, ordered by the process-bigraph scheduler via
input/output store wiring. Design:
``docs/superpowers/specs/2026-08-01-investigation-as-composite-design.md`` (§3).

Pure dict construction — deliberately imports NO ``process_bigraph`` (the Step
classes are referenced only by ``local:<Class>`` string address), so this module
+ its shape tests stay import-light.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from vivarium_workbench.lib.investigation_members import (
    investigation_member_slugs,
    member_slug,
)
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _study_prereqs(ws: WorkspacePaths, slug: str) -> list[str]:
    """Study-slugs ``slug`` must run after, read STRICTLY from
    ``pipeline_gate.prerequisites`` — NOT the legacy ``parent_studies`` fallback.
    Mirrors ``prepare_investigation._study_prereqs`` (#712, 5126f15b): each entry
    is a dict ``{study: X, ...}`` or a bare string ``X``. Keying strictly on this
    field makes reading a no-``pipeline_gate`` study.yaml a no-op (empty list)
    rather than silently picking up legacy ``parent_studies`` edges."""
    p = ws.studies / slug / "study.yaml"
    if not p.exists():
        return []
    spec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    gate = spec.get("pipeline_gate") or {}
    prereqs = gate.get("prerequisites") or []
    out: list[str] = []
    for e in prereqs:
        if isinstance(e, dict) and e.get("study"):
            out.append(e["study"])
        elif isinstance(e, str) and e:
            out.append(e)
    return out


def build_investigation_composite(ws_root: Path | str, inv_slug: str) -> dict:
    """Compile ``investigations/<inv_slug>/investigation.yaml`` into a composite
    state dict: one ``StudyStep`` per member study (prerequisite-ordered, real or
    synthetic-serial) + one ``InvestigationAnalysisStep`` per ``analyses:`` entry
    wired to every member study's result store.

    Ordering has two mechanisms, both expressed purely as input wires (no explicit
    scheduling code — ``process_bigraph``'s ``determine_steps`` reads the wires):

    1. **Real prerequisites** — a study's ``pipeline_gate.prerequisites``, filtered
       to entries that are members of THIS investigation.
    2. **Synthetic serial edges** — confirmed necessary in Task 1: independent
       steps (no wiring between them) run in NONDETERMINISTIC engine order, not
       declared order. A study with no real prerequisite is wired instead to the
       immediately-preceding declared member, turning a whole no-prerequisite
       investigation into a deterministic declared-order chain. (v1 is serial;
       dropping these edges for genuinely-independent studies is a later
       parallelism pass.)

    Returns a plain state dict (NOT a running ``Composite``) — callers wrap it as
    ``Composite({"state": build_investigation_composite(...),
    "run_steps_on_init": True}, core)``.
    """
    ws = WorkspacePaths.load(ws_root)
    ws_root_str = str(ws_root)
    inv_path = ws.investigations / inv_slug / "investigation.yaml"
    spec = yaml.safe_load(inv_path.read_text(encoding="utf-8")) or {}

    members: list[str] = []
    for entry in investigation_member_slugs(spec):
        slug = member_slug(entry)
        if slug:
            members.append(slug)
    member_set = set(members)

    state: dict[str, Any] = {}

    for i, slug in enumerate(members):
        real_prereqs = [
            p for p in _study_prereqs(ws, slug) if p in member_set and p != slug
        ]
        if real_prereqs:
            prereqs = real_prereqs
        elif i > 0:
            # No real prerequisite: synthetic serial edge to the
            # immediately-preceding declared member (declared-order determinism
            # — see function docstring).
            prereqs = [members[i - 1]]
        else:
            prereqs = []

        state[slug] = {
            "_type": "step",
            "address": "local:StudyStep",
            "config": {
                "workspace": ws_root_str,
                "study_slug": slug,
                "prereqs": prereqs,
            },
            "inputs": {f"prereq_{p}": [f"study_{p}_result"] for p in prereqs},
            "outputs": {"result": [f"study_{slug}_result"]},
        }
        state[f"study_{slug}_result"] = {}

    report_dir_str = str(ws.report_dir(inv_slug))
    for entry in (spec.get("analyses") or []):
        name = entry.get("name") if isinstance(entry, dict) else entry
        if not name:
            continue
        params = (entry.get("params") if isinstance(entry, dict) else None) or {}

        state[f"analysis_{name}"] = {
            "_type": "step",
            "address": "local:InvestigationAnalysisStep",
            "config": {
                "workspace": ws_root_str,
                "name": name,
                "params": params,
                "study_slugs": list(members),
                "report_dir": report_dir_str,
            },
            "inputs": {
                f"study_{slug}": [f"study_{slug}_result"] for slug in members
            },
            "outputs": {"written": [f"analysis_{name}_written"]},
        }
        state[f"analysis_{name}_written"] = {}

    return state

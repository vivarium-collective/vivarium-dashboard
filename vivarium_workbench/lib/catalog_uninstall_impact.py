"""What an ``uninstall`` of a catalog module would remove from THIS workspace.

Backs ``GET /api/catalog-uninstall-impact?name=<module>`` — the pre-uninstall
confirmation the Modules tab shows before actually removing an imported module.
Two kinds of impact are surfaced so the user can decide with eyes open:

  1. **Module content that disappears** — the composites, studies, and
     investigations the module itself contributes to the workspace (its
     federated ``external/<name>/`` content plus any packaged composites).
     Uninstalling removes the import, so all of this stops showing up.

  2. **This workspace's own content that references it** — the workspace's OWN
     studies whose ``baseline``/``variants`` point at one of the module's
     composites, and the workspace's OWN investigations that list one of the
     module's federated studies as a member. These don't vanish, but they
     break: a dangling composite / study reference. This is the "what will I
     break" signal, distinct from "what will I lose".

Keyed by :func:`~vivarium_workbench.lib.module_stats._norm` of the module
identity, mirroring ``module_content_stats`` so the two views agree.

Best-effort throughout: any failure degrades to an empty impact (never raises)
so a malformed linked workspace or study spec can't wedge the uninstall flow.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib.federation import (
    federated_composites,
    federated_investigation_sets,
    federated_studies,
)
from vivarium_workbench.lib.investigation_members import investigation_member_slugs
from vivarium_workbench.lib.module_stats import (
    _installed_composites_by_norm,
    _norm,
)
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _own_references_detail(ws_root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Reverse index of THIS workspace's own references, for impact reporting.

    Returns ``(composite_refs, study_refs)`` where:

      * ``composite_refs[composite_id]`` = set of own study slugs whose
        ``baseline``/``variants`` reference that composite id.
      * ``study_refs[federated_study_id]`` = set of own investigation slugs
        whose membership list references that ``<repo>::<study>`` id.

    The detailed cousin of :func:`module_stats._own_referenced_ids` (which
    returns only the flat id set). Best-effort: malformed specs are skipped.
    """
    ws_root = Path(ws_root)
    composite_refs: dict[str, set[str]] = {}
    study_refs: dict[str, set[str]] = {}

    try:
        wp = WorkspacePaths.load(ws_root)
    except Exception:
        return composite_refs, study_refs

    try:
        from vivarium_workbench.lib.investigations import load_spec as _load_study_spec
    except Exception:
        _load_study_spec = None

    if _load_study_spec is not None:
        try:
            for sdir in wp.iter_study_dirs():
                f = sdir / "study.yaml"
                if not f.is_file():
                    f = sdir / "spec.yaml"
                if not f.is_file():
                    continue
                try:
                    spec = _load_study_spec(f)
                except Exception:
                    continue
                if not isinstance(spec, dict):
                    continue
                slug = sdir.name
                for key in ("baseline", "variants"):
                    for entry in (spec.get(key) or []):
                        if isinstance(entry, dict) and entry.get("composite"):
                            composite_refs.setdefault(str(entry["composite"]), set()).add(slug)
        except Exception:
            pass

    try:
        idir = wp.investigations
        if idir.is_dir():
            for d in idir.iterdir():
                if not d.is_dir():
                    continue
                f = d / "investigation.yaml"
                if not f.is_file():
                    continue
                try:
                    spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                except Exception:
                    continue
                if not isinstance(spec, dict):
                    continue
                for item in investigation_member_slugs(spec):
                    ref = (
                        item if isinstance(item, str)
                        else (item or {}).get("study") or (item or {}).get("slug")
                    )
                    if ref and "::" in str(ref):
                        study_refs.setdefault(str(ref), set()).add(d.name)
    except Exception:
        pass

    return composite_refs, study_refs


def module_uninstall_impact(ws_root: Path, name: str) -> dict:
    """Impact of uninstalling catalog module ``name`` from ``ws_root``.

    Returns a JSON-serializable dict::

        {
          "module": "pbg-copasi",
          "module_content": {
            "composites":     ["pbg_copasi.composites.foo", ...],
            "studies":        ["pbg-copasi::glycolysis", ...],
            "investigations": ["pbg-copasi::overflow", ...],
          },
          "workspace_refs": {
            "studies":        [{"study": "my-study", "composite": "pbg_copasi.composites.foo"}],
            "investigations": [{"investigation": "my-inv", "study": "pbg-copasi::glycolysis"}],
          },
          "has_impact": true
        }

    ``module_content`` is what stops showing up; ``workspace_refs`` is the
    workspace's OWN content that would be left with a dangling reference.
    Never raises — degrades to an all-empty impact.
    """
    ws_root = Path(ws_root)
    key = _norm(name)

    module_composites: set[str] = set()
    module_studies: set[str] = set()
    module_investigations: set[str] = set()

    try:
        for spec_id, rec in federated_composites(ws_root).items():
            if _norm(rec.get("origin_repo")) == key:
                module_composites.add(spec_id)
    except Exception:
        pass
    try:
        module_composites |= _installed_composites_by_norm().get(key, set())
    except Exception:
        pass
    try:
        for s in federated_studies(ws_root):
            if _norm(s.get("origin_repo")) == key and s.get("id"):
                module_studies.add(str(s["id"]))
    except Exception:
        pass
    try:
        for iset in federated_investigation_sets(ws_root):
            if _norm(iset.get("origin_repo")) == key and iset.get("id"):
                module_investigations.add(str(iset["id"]))
    except Exception:
        pass

    composite_refs, study_refs = _own_references_detail(ws_root)

    ref_studies = [
        {"study": slug, "composite": cid}
        for cid in sorted(module_composites)
        for slug in sorted(composite_refs.get(cid, set()))
    ]
    ref_investigations = [
        {"investigation": slug, "study": sid}
        for sid in sorted(module_studies)
        for slug in sorted(study_refs.get(sid, set()))
    ]

    module_content = {
        "composites": sorted(module_composites),
        "studies": sorted(module_studies),
        "investigations": sorted(module_investigations),
    }
    has_impact = bool(
        module_composites or module_studies or module_investigations
        or ref_studies or ref_investigations
    )

    return {
        "module": name,
        "module_content": module_content,
        "workspace_refs": {
            "studies": ref_studies,
            "investigations": ref_investigations,
        },
        "has_impact": has_impact,
    }

"""Per-module content counts + this workspace's usage of that content.

Powers the "module cards — content counts + workspace usage" feature: each
card in the Registry -> Modules grid / Marketplace tab shows how many
composites/studies/investigations a linked module ships, and how many of
those items THIS workspace's own studies/investigations actually reference
(the "we depend on this" signal, distinct from merely being installed).

Two content sources are merged, keyed by a normalized module identity
(:func:`_norm`) so the join survives the catalog's inconsistent naming
(dashed vs underscored vs mixed case -- "pbg-copasi", "pbg_ketchup",
"Viva-munk"):

  - ``lib/federation.py``'s read-only scan of linked workspaces (modules
    landed at ``<ws_root>/external/<name>/`` with their own
    ``workspace.yaml``) -- composites, studies, AND investigations.
  - installed distributions' packaged ``<pkg>/composites/*.composite.*``
    files (via ``lib/composite_lookup.discover_installed_composites_all``)
    -- composites only; a wheel/venv install has no on-disk studies or
    investigations to count, since those live in a workspace, not a package.

This is what makes module cards meaningful on a workspace like v2ecoli that
has no ``external/`` links at all (everything wheel/venv-installed) --
previously such a workspace always showed 0 composites/studies/investigations
because the function short-circuited on "no linked workspaces".

Best-effort throughout: any failure for one module, or the whole
computation, degrades to an empty result rather than raising, so a malformed
linked workspace, study spec, or installed distribution never breaks the
catalog/marketplace payload.
"""
from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

import yaml

from vivarium_workbench.lib.composite_lookup import discover_installed_composites_all
from vivarium_workbench.lib.federation import (
    federated_composites,
    federated_investigation_sets,
    federated_studies,
    linked_workspaces,
)
from vivarium_workbench.lib.investigation_members import investigation_member_slugs
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _norm(name: str | None) -> str:
    """Normalize a module/package identity for cross-source joins.

    Catalog module names are inconsistent (dashed, underscored, mixed case:
    "pbg-copasi" / "pbg_ketchup" / "Viva-munk" / "spatio-flux"), while
    composite spec ids always embed the canonical importable package name
    (``pkg_name.composites.stem``). Lowercase, strip, dashes -> underscores,
    and take the first dot-segment so any trailing dotted suffix doesn't
    break the match. Empty/None input normalizes to ``""``.
    """
    if not name:
        return ""
    return str(name).strip().lower().replace("-", "_").split(".", 1)[0]


def _installed_composites_by_norm() -> dict[str, set[str]]:
    """Packaged composite spec ids from every installed distribution, grouped
    by :func:`_norm` of the owning package name.

    Best-effort: degrades to ``{}`` on any failure (never raises), matching
    :func:`discover_installed_composites_all`'s own per-distribution
    best-effort contract.
    """
    out: dict[str, set[str]] = {}
    try:
        specs = discover_installed_composites_all()
    except Exception:
        return out
    for spec_id in specs:
        pkg = spec_id.split(".composites.", 1)[0] if ".composites." in spec_id else None
        if not pkg:
            continue
        out.setdefault(_norm(pkg), set()).add(spec_id)
    return out


def _last_updated(root: Path) -> str | None:
    """Best-effort ISO-8601 timestamp for a module's on-disk root.

    Prefers the git HEAD commit date (no fetch -- purely local); falls back
    to the newest file mtime under `root`; returns None if both fail (e.g.
    an empty or unreadable directory).
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=root, capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            if out:
                return out
    except Exception:
        pass
    try:
        newest: float | None = None
        for p in root.rglob("*"):
            try:
                if p.is_file():
                    mt = p.stat().st_mtime
                    if newest is None or mt > newest:
                        newest = mt
            except OSError:
                continue
        if newest is not None:
            return datetime.datetime.fromtimestamp(
                newest, tz=datetime.timezone.utc
            ).isoformat()
    except Exception:
        pass
    return None


def _own_referenced_ids(ws_root: Path) -> set[str]:
    """Item ids referenced by THIS workspace's own studies/investigations.

    Collects:
      - composite ids from own study specs' ``baseline[].composite`` /
        ``variants[].composite`` (after full load_spec migration, so v2/v3/v4
        study shapes are all normalized to the same legacy-projected view).
      - federated study ids (``<repo>::<study>``) referenced by own
        investigation.yaml ``studies:``/``members:`` membership lists.

    Best-effort: a malformed spec is skipped, never raises.
    """
    ws_root = Path(ws_root)
    out: set[str] = set()

    try:
        wp = WorkspacePaths.load(ws_root)
    except Exception:
        return out

    # Local import: investigations.py is heavier (spec migration/validation)
    # than this leaf module's other deps, and isn't needed on every caller of
    # workspace_paths/federation, so keep the import scoped to this function.
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
                for entry in (spec.get("baseline") or []):
                    if isinstance(entry, dict) and entry.get("composite"):
                        out.add(str(entry["composite"]))
                for entry in (spec.get("variants") or []):
                    if isinstance(entry, dict) and entry.get("composite"):
                        out.add(str(entry["composite"]))
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
                    slug = (
                        item if isinstance(item, str)
                        else (item or {}).get("study") or (item or {}).get("slug")
                    )
                    if slug and "::" in str(slug):
                        out.add(str(slug))
    except Exception:
        pass

    return out


def module_content_stats(ws_root: Path) -> dict[str, dict]:
    """Per-module content counts + this workspace's usage, keyed by
    :func:`_norm` of the module identity (the linked workspace's
    ``workspace.yaml`` ``name`` -- the same value ``federated_*`` tags as
    ``origin_repo`` -- or, for wheel/venv-only modules, the installed
    package name; both are the catalog module entry's ``name`` under a
    different spelling convention, hence the normalization).

    Each value: ``{n_composites, n_investigations, n_studies, n_used,
    last_updated}``. ``n_composites`` unions federated (linked-workspace)
    composites with installed-package composites, so a wheel-only module's
    packaged ``composites/`` dir counts even with no ``external/`` link.
    ``n_studies``/``n_investigations`` come from the external federation scan
    only -- a wheel install has no on-disk studies/investigations, so those
    legitimately stay 0 for wheel-only modules. A module with no content
    from EITHER source simply doesn't appear in the returned dict --
    callers should treat a missing key as all-zero/None.

    Never raises: any failure degrades to ``{}`` (or omits the offending
    module) so callers -- `build_catalog` -- always get a usable result.
    """
    ws_root = Path(ws_root)
    stats: dict[str, dict] = {}

    try:
        links = linked_workspaces(ws_root)
    except Exception:
        links = []

    comps_by_norm: dict[str, set[str]] = {}
    try:
        for spec_id, rec in federated_composites(ws_root).items():
            repo = rec.get("origin_repo")
            if repo:
                comps_by_norm.setdefault(_norm(repo), set()).add(spec_id)
    except Exception:
        pass

    studies_by_norm: dict[str, set[str]] = {}
    try:
        for s in federated_studies(ws_root):
            repo = s.get("origin_repo")
            if repo and s.get("id"):
                studies_by_norm.setdefault(_norm(repo), set()).add(s["id"])
    except Exception:
        pass

    n_investigations_by_norm: dict[str, int] = {}
    try:
        for iset in federated_investigation_sets(ws_root):
            repo = iset.get("origin_repo")
            if repo:
                key = _norm(repo)
                n_investigations_by_norm[key] = n_investigations_by_norm.get(key, 0) + 1
    except Exception:
        pass

    last_updated_by_norm: dict[str, str | None] = {}
    for lw in links:
        try:
            last_updated_by_norm[_norm(lw.repo)] = _last_updated(lw.root)
        except Exception:
            continue

    installed_comps_by_norm = _installed_composites_by_norm()

    all_norm_keys = (
        set(comps_by_norm)
        | set(studies_by_norm)
        | set(n_investigations_by_norm)
        | set(installed_comps_by_norm)
    )
    all_norm_keys.discard("")

    module_ids_by_norm: dict[str, set[str]] = {}
    for key in all_norm_keys:
        try:
            composite_ids = comps_by_norm.get(key, set()) | installed_comps_by_norm.get(key, set())
            study_ids = studies_by_norm.get(key, set())
            n_inv = n_investigations_by_norm.get(key, 0)
            if not composite_ids and not study_ids and not n_inv:
                continue
            module_ids_by_norm[key] = composite_ids | study_ids
            stats[key] = {
                "n_composites": len(composite_ids),
                "n_investigations": n_inv,
                "n_studies": len(study_ids),
                "n_used": 0,
                "last_updated": last_updated_by_norm.get(key),
            }
        except Exception:
            continue

    if not stats:
        return stats

    try:
        referenced = _own_referenced_ids(ws_root)
    except Exception:
        referenced = set()

    if referenced:
        for key, rec in stats.items():
            module_ids = module_ids_by_norm.get(key, set())
            rec["n_used"] = len(module_ids & referenced)

    return stats

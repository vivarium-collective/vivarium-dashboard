"""Per-module content counts + this workspace's usage of that content.

Powers the "module cards — content counts + workspace usage" feature: each
card in the Registry -> Modules grid / Marketplace tab shows how many
composites/studies/investigations a linked module ships, and how many of
those items THIS workspace's own studies/investigations actually reference
(the "we depend on this" signal, distinct from merely being installed).

Built entirely on top of ``lib/federation.py``'s read-only scan of linked
workspaces (modules landed at ``<ws_root>/external/<name>/`` with their own
``workspace.yaml``) -- no new discovery mechanism. Best-effort throughout:
any failure for one module, or the whole computation, degrades to an empty
result rather than raising, so a malformed linked workspace or study spec
never breaks the catalog/marketplace payload.
"""
from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

import yaml

from vivarium_workbench.lib.federation import (
    federated_composites,
    federated_investigation_sets,
    federated_studies,
    linked_workspaces,
)
from vivarium_workbench.lib.investigation_members import investigation_member_slugs
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


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
    """Per-linked-module content counts + this workspace's usage, keyed by
    module display name (the linked workspace's ``workspace.yaml`` ``name``
    -- the same value ``federated_*`` tags as ``origin_repo``, which is also
    the catalog module entry's ``name``).

    Each value: ``{n_composites, n_investigations, n_studies, n_used,
    last_updated}``. A module with no linked (full-repo-installed) content on
    disk simply doesn't appear in the returned dict -- callers should treat
    a missing key as all-zero/None (wheel-only / available-to-install
    modules have no on-disk studies/investigations to count).

    Never raises: any failure degrades to ``{}`` (or omits the offending
    module) so callers -- `build_catalog` -- always get a usable result.
    """
    ws_root = Path(ws_root)
    stats: dict[str, dict] = {}

    try:
        links = linked_workspaces(ws_root)
    except Exception:
        links = []
    if not links:
        return stats

    comps_by_repo: dict[str, set[str]] = {}
    try:
        for spec_id, rec in federated_composites(ws_root).items():
            repo = rec.get("origin_repo")
            if repo:
                comps_by_repo.setdefault(repo, set()).add(spec_id)
    except Exception:
        pass

    studies_by_repo: dict[str, set[str]] = {}
    try:
        for s in federated_studies(ws_root):
            repo = s.get("origin_repo")
            if repo and s.get("id"):
                studies_by_repo.setdefault(repo, set()).add(s["id"])
    except Exception:
        pass

    n_investigations_by_repo: dict[str, int] = {}
    try:
        for iset in federated_investigation_sets(ws_root):
            repo = iset.get("origin_repo")
            if repo:
                n_investigations_by_repo[repo] = n_investigations_by_repo.get(repo, 0) + 1
    except Exception:
        pass

    module_ids_by_repo: dict[str, set[str]] = {}
    for lw in links:
        try:
            repo = lw.repo
            composite_ids = comps_by_repo.get(repo, set())
            study_ids = studies_by_repo.get(repo, set())
            module_ids_by_repo[repo] = composite_ids | study_ids
            stats[repo] = {
                "n_composites": len(composite_ids),
                "n_investigations": n_investigations_by_repo.get(repo, 0),
                "n_studies": len(study_ids),
                "n_used": 0,
                "last_updated": _last_updated(lw.root),
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
        for repo, rec in stats.items():
            module_ids = module_ids_by_repo.get(repo, set())
            rec["n_used"] = len(module_ids & referenced)

    return stats

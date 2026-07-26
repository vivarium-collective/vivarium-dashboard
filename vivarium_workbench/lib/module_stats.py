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
import re
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


def _own_module_usage(ws_root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Per-study module usage from THIS workspace's own studies, two maps:

    ``study_refs[slug]`` -- the composite ids study ``slug`` references in its
    ``baseline``/``variants`` (migrated spec view, so v2/v3/v4 shapes normalize
    the same). The caller attributes each id to a module both by its package
    prefix (``pbg_ketchup.composites.…`` -> ``pbg_ketchup``, which catches
    Python ``@composite_generator`` modules that file-discovery misses) and by
    whichever module's federated/installed content set contains it (which
    catches federated modules whose composite ids don't embed the module name).

    ``study_uses[slug]`` -- normalized module identities from an explicit
    top-level ``uses_modules:`` list in ``study.yaml``. The escape hatch for
    modules used only through a runner script / process wiring, which leave no
    composite reference in the spec (e.g. ``pbg-torch`` assembling a
    ``TransitionDataset`` in a surrogate study's runner).

    Best-effort: a malformed spec is skipped, never raises.
    """
    ws_root = Path(ws_root)
    study_refs: dict[str, set[str]] = {}
    study_uses: dict[str, set[str]] = {}

    try:
        wp = WorkspacePaths.load(ws_root)
    except Exception:
        return study_refs, study_uses

    try:
        from vivarium_workbench.lib.investigations import load_spec as _load_study_spec
    except Exception:
        _load_study_spec = None

    try:
        study_dirs = list(wp.iter_study_dirs())
    except Exception:
        study_dirs = []

    for sdir in study_dirs:
        f = sdir / "study.yaml"
        if not f.is_file():
            f = sdir / "spec.yaml"
        if not f.is_file():
            continue
        slug = sdir.name

        # (a) composite references, via the migrated spec view.
        if _load_study_spec is not None:
            try:
                spec = _load_study_spec(f)
            except Exception:
                spec = None
            if isinstance(spec, dict):
                for section in ("baseline", "variants"):
                    for entry in (spec.get(section) or []):
                        if isinstance(entry, dict) and entry.get("composite"):
                            study_refs.setdefault(slug, set()).add(str(entry["composite"]))

        # (b) explicit `uses_modules:` -- read from RAW yaml so a new top-level
        # field survives regardless of what the migrated schema keeps.
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            for mod in (raw.get("uses_modules") or []):
                nk = _norm(mod if isinstance(mod, str) else (mod or {}).get("name"))
                if nk:
                    study_uses.setdefault(slug, set()).add(nk)

    return study_refs, study_uses


def _installed_module_pkgs(ws_root: Path) -> set[str]:
    """Normalized package names of every module this workspace has installed --
    ``workspace.yaml`` imports + ``pyproject.toml`` dependencies. The scan target
    set for :func:`_deep_module_usage`. Over-inclusion is harmless: a package
    that isn't a catalog module simply never matches a card."""
    pkgs: set[str] = set()
    try:
        w = yaml.safe_load((Path(ws_root) / "workspace.yaml").read_text(encoding="utf-8")) or {}
        imp = w.get("imports") or {}
        if isinstance(imp, dict):
            for k, v in imp.items():
                pkgs.add(_norm((v or {}).get("package") if isinstance(v, dict) else None) or _norm(k))
    except Exception:
        pass
    try:
        import tomllib
        pp = tomllib.loads((Path(ws_root) / "pyproject.toml").read_text(encoding="utf-8"))
        for dep in (pp.get("project", {}).get("dependencies") or []):
            name = re.split(r"[<>=!~;\s\[]", str(dep), 1)[0].strip()
            if name:
                pkgs.add(_norm(name))
    except Exception:
        pass
    pkgs.discard("")
    return pkgs


def _composite_source_file(cid: str, ws_root: Path) -> "Path | None":
    """Best-effort source file for a fully-qualified composite id
    (``pkg.composites.stem[.Class]``): ``pkg/composites/stem.py`` or
    ``pkg/composites/stem/__init__.py`` under ``ws_root``. ``None`` for a bare
    clean-alias id (no ``.composites.``) whose file can't be derived."""
    if ".composites." not in cid:
        return None
    pkg, _, rest = cid.partition(".composites.")
    stem = rest.split(".")[0]
    base = Path(ws_root) / pkg.replace(".", "/") / "composites"
    for cand in (base / (stem + ".py"), base / stem / "__init__.py"):
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def _deep_module_usage(ws_root: Path, study_refs: dict[str, set[str]]) -> dict[str, set[str]]:
    """Deeper study->module usage the composite-id package prefix alone misses:

    1. **Composite-source scan** -- a study's composite generator wires in
       processes from OTHER modules by import or address string (e.g. the
       ``ecoli_colony`` composite drives ``viva_munk``'s ``PymunkProcess``).
       Scan each referenced composite's generator source for any installed
       module's package name and credit the study.
    2. **Runtime default emitter** -- every run emits through
       ``workspace.yaml::runtime.default_emitter`` (the emitter classes live in
       ``pbg_emitters`` / ``viva-emitters``, a base dep). So the emitter module
       is used by EVERY study. Credit it to all of them.

    Returns ``used_by_studies``-shaped ``dict[norm] -> set(study_slug)``. Coarse
    but cheap (static text scan, no build_core); never raises.
    """
    out: dict[str, set[str]] = {}
    try:
        candidates = _installed_module_pkgs(ws_root)
    except Exception:
        candidates = set()

    # (1) composite-source scan, per study.
    _src_cache: dict[str, set[str]] = {}
    for slug, cids in (study_refs or {}).items():
        for cid in cids:
            hits = _src_cache.get(cid)
            if hits is None:
                hits = set()
                f = _composite_source_file(cid, ws_root)
                if f is not None:
                    try:
                        txt = f.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        txt = ""
                    for pkg in candidates:
                        # pkg is already _norm'd (underscores); source uses the
                        # importable underscore form.
                        if pkg and re.search(r"\b" + re.escape(pkg) + r"\b", txt):
                            hits.add(pkg)
                _src_cache[cid] = hits
            for nk in hits:
                out.setdefault(nk, set()).add(slug)

    # (2) runtime default emitter -> used by every study.
    try:
        w = yaml.safe_load((Path(ws_root) / "workspace.yaml").read_text(encoding="utf-8")) or {}
        default_emitter = ((w.get("runtime") or {}).get("default_emitter") or "").strip()
    except Exception:
        default_emitter = ""
    if default_emitter:
        all_slugs: set[str] = set(study_refs or {})
        try:
            from vivarium_workbench.lib.workspace_paths import WorkspacePaths
            for sdir in WorkspacePaths.load(ws_root).iter_study_dirs():
                all_slugs.add(sdir.name)
        except Exception:
            pass
        # The emitter framework module (pbg-emitters / viva-emitters) provides the
        # default emitter every run uses. Credit whichever emitter package the
        # workspace actually installed.
        for emitter_pkg in ("pbg_emitters", "viva_emitters"):
            if emitter_pkg in candidates and all_slugs:
                out.setdefault(emitter_pkg, set()).update(all_slugs)

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

    # n_repos: how many repos import each module — this workspace plus every
    # linked workspace whose workspace.yaml `imports` names it. Answers "how many
    # repos is this module imported into" across the federated ecosystem.
    repos_by_norm: dict[str, set[str]] = {}

    def _add_imports(repo_label: str, ws_data: dict | None) -> None:
        imports = (ws_data or {}).get("imports", {}) or {}
        keys = imports.keys() if isinstance(imports, dict) else (imports if isinstance(imports, list) else [])
        rk = _norm(repo_label)
        for k in keys:
            nk = _norm(str(k))
            if nk and rk:
                repos_by_norm.setdefault(nk, set()).add(rk)

    try:
        _own = yaml.safe_load((ws_root / "workspace.yaml").read_text(encoding="utf-8")) or {}
        _add_imports(_own.get("name") or ws_root.name, _own)
    except Exception:
        pass
    for lw in links:
        try:
            _add_imports(lw.repo, yaml.safe_load((lw.root / "workspace.yaml").read_text(encoding="utf-8")) or {})
        except Exception:
            continue

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

    # Reference-driven usage: which imported modules THIS workspace's own studies
    # actually use. Attribute each study to a module by (1) the package prefix of
    # a composite id it references (catches Python @composite_generator modules
    # that file-discovery misses, e.g. pbg-ketchup), (2) whichever module's
    # federated/installed content set contains that id (catches federated modules
    # whose composite ids don't embed the module name), and (3) an explicit
    # `uses_modules:` list (catches modules used only via a runner script, e.g.
    # pbg-torch). `n_used` then counts THIS workspace's own studies -- not items.
    try:
        study_refs, study_uses = _own_module_usage(ws_root)
    except Exception:
        study_refs, study_uses = {}, {}

    # Reverse index: composite/study item id -> the module norms that own it.
    item_to_norms: dict[str, set[str]] = {}
    for _by in (comps_by_norm, installed_comps_by_norm, studies_by_norm):
        for _nk, _ids in _by.items():
            for _id in _ids:
                item_to_norms.setdefault(_id, set()).add(_nk)

    used_by_studies: dict[str, set[str]] = {}
    ref_comps_by_norm: dict[str, set[str]] = {}   # referenced composites, by module (for n_composites)
    for slug, cids in study_refs.items():
        for cid in cids:
            pkg = cid.split(".composites.", 1)[0] if ".composites." in cid else cid
            attribute = set(item_to_norms.get(cid, set()))
            pfx = _norm(pkg)
            if pfx:
                attribute.add(pfx)
                if ".composites." in cid:
                    ref_comps_by_norm.setdefault(pfx, set()).add(cid)
            for nk in attribute:
                used_by_studies.setdefault(nk, set()).add(slug)
    for slug, norms in study_uses.items():
        for nk in norms:
            used_by_studies.setdefault(nk, set()).add(slug)

    # Deeper usage: composite-source scan (a composite wiring another module's
    # processes, e.g. ecoli_colony -> viva_munk) + the runtime default emitter
    # (pbg-emitters/viva-emitters, used by every run). Merge in.
    try:
        for nk, slugs in _deep_module_usage(ws_root, study_refs).items():
            if nk:
                used_by_studies.setdefault(nk, set()).update(slugs)
    except Exception:
        pass

    all_norm_keys = (
        set(comps_by_norm)
        | set(studies_by_norm)
        | set(n_investigations_by_norm)
        | set(installed_comps_by_norm)
        | set(ref_comps_by_norm)
        | set(used_by_studies)
        | set(repos_by_norm)
    )
    all_norm_keys.discard("")

    for key in all_norm_keys:
        try:
            composite_ids = (
                comps_by_norm.get(key, set())
                | installed_comps_by_norm.get(key, set())
                | ref_comps_by_norm.get(key, set())
            )
            study_ids = studies_by_norm.get(key, set())
            n_inv = n_investigations_by_norm.get(key, 0)
            n_used = len(used_by_studies.get(key, set()))
            n_repos = len(repos_by_norm.get(key, set()))
            if not composite_ids and not study_ids and not n_inv and not n_used and not n_repos:
                continue
            stats[key] = {
                "n_composites": len(composite_ids),
                "n_investigations": n_inv,
                "n_studies": len(study_ids),
                "n_used": n_used,
                "n_repos": n_repos,
                "last_updated": last_updated_by_norm.get(key),
            }
        except Exception:
            continue

    return stats

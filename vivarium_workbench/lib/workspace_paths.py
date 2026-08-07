"""Canonical resolution of a workspace's directory layout.

Every workspace has a set of well-known directories — ``studies/``,
``investigations/``, ``composites/``, ``references/``, ``.pbg/``, the Python
package, etc. Historically each of these names was hardcoded as a string
literal at ~150 call sites across the dashboard, the pbg-superpowers skills,
and ``lint-workspace.py``. This module is the single place that knows the
layout, so the physical location of any directory can be changed in one spot
(an optional ``layout:`` map in ``workspace.yaml``) instead of everywhere.

Backward compatibility: a key left out of ``layout:`` falls back to the
conventional flat name (``studies`` -> ``studies/``). A workspace with no
``layout:`` block at all therefore keeps the classic top-level layout, so all
existing workspaces are unaffected.

Example ``workspace.yaml`` to nest research dirs under ``workspace/``::

    layout:
      studies: workspace/studies
      investigations: workspace/investigations
      composites: workspace/composites
      references: workspace/references
      datasets: workspace/datasets
      reports: workspace/reports
      pbg: workspace/.pbg
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

import yaml

from vivarium_workbench.lib.investigation_members import investigation_member_slugs

# The canonical flat layout — the single source of truth for directory names.
# Keys are logical names used throughout the codebase; values are the default
# workspace-root-relative paths. The Python package (`package`) is special: it
# derives from `package_path`/`name` in workspace.yaml, so it has no fixed
# default here.
LAYOUT_DEFAULTS: dict[str, str] = {
    "studies": "studies",
    "investigations": "investigations",
    "composites": "composites",
    "references": "references",
    "datasets": "datasets",
    "reports": "reports",
    "pbg": ".pbg",
    "scripts": "scripts",
    "tests": "tests",
    "docs": "docs",
}

# Logical names a workspace may override via `layout:` (`package` is normally
# set through `package_path`, but may also be relocated via `layout`).
LAYOUT_KEYS = tuple(LAYOUT_DEFAULTS) + ("package",)


# mtime-keyed memo for ``WorkspacePaths.load``. ``load`` is called ~126 times
# across the dashboard, and each call previously re-``stat``ed, re-read, and
# re-parsed ``workspace.yaml``. The layout almost never changes within a server
# lifetime, so we cache the resolved ``WorkspacePaths`` keyed by the resolved
# root path, tagged with the ``workspace.yaml`` mtime (ns) used to build it.
# A cached entry is reused only while that mtime is unchanged; any edit to the
# file (or its creation/deletion) changes the mtime tag and forces a re-parse,
# so the cache stays correct. Not guarded by a lock: a benign race just
# re-parses. ``_parse_count`` is a test hook incremented on each real parse.
_LOAD_CACHE: dict[str, tuple[Optional[int], "WorkspacePaths"]] = {}
_parse_count = 0


def _clear_load_cache() -> None:
    """Drop the ``WorkspacePaths.load`` memo (test/utility helper)."""
    _LOAD_CACHE.clear()


def package_slug(name: str | None) -> str:
    """Default Python package directory for a workspace named `name`."""
    return f"pbg_{(name or 'workspace').replace('-', '_')}"


@dataclass(frozen=True)
class WorkspacePaths:
    """Resolved directory layout for a single workspace.

    Construct via :meth:`load` (reads ``workspace.yaml``) or :meth:`from_config`
    (caller supplies the parsed dict). Access directories by attribute
    (``wp.studies``) or by name (``wp.dir("studies")``). Subpaths are formed by
    joining onto the result, e.g. ``wp.pbg / "schemas"`` or
    ``wp.reports / "figures" / study``.
    """

    root: Path
    _layout: Mapping[str, str]

    @classmethod
    def from_config(cls, root: Path | str, config: Optional[Mapping] = None) -> "WorkspacePaths":
        config = dict(config or {})
        layout = dict(LAYOUT_DEFAULTS)
        # Package directory: explicit package_path wins, else derive from name.
        layout["package"] = config.get("package_path") or package_slug(config.get("name"))
        # Apply explicit per-directory overrides.
        overrides = config.get("layout") or {}
        for key, value in overrides.items():
            if key in LAYOUT_KEYS and isinstance(value, str) and value:
                layout[key] = value
        return cls(Path(root).resolve(), layout)

    @classmethod
    def load(cls, root: Path | str) -> "WorkspacePaths":
        """Resolve layout from ``<root>/workspace.yaml`` (empty if missing).

        Memoized by resolved root + ``workspace.yaml`` mtime: a repeated load
        with an unchanged file returns the cached instance without re-parsing;
        a changed (or newly created/deleted) file invalidates the entry.
        """
        root = Path(root)
        resolved = str(root.resolve())
        wf = root / "workspace.yaml"
        try:
            mtime: Optional[int] = wf.stat().st_mtime_ns
        except OSError:
            # Missing (or unreadable) workspace.yaml -> empty config. Tag with
            # None so a later creation (mtime becomes an int) invalidates.
            mtime = None
        cached = _LOAD_CACHE.get(resolved)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        config: dict = {}
        if mtime is not None:
            config = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
            global _parse_count
            _parse_count += 1
        wp = cls.from_config(root, config)
        _LOAD_CACHE[resolved] = (mtime, wp)
        return wp

    def dir(self, name: str) -> Path:
        """Absolute path to the directory registered under logical `name`."""
        if name not in self._layout:
            raise KeyError(f"unknown workspace directory: {name!r}")
        return self.root / self._layout[name]

    def rel(self, name: str) -> str:
        """Workspace-root-relative path string for logical `name`."""
        return self._layout[name]

    # Convenience accessors -------------------------------------------------
    @property
    def studies(self) -> Path: return self.dir("studies")
    @property
    def investigations(self) -> Path: return self.dir("investigations")
    @property
    def composites(self) -> Path: return self.dir("composites")
    @property
    def references(self) -> Path: return self.dir("references")
    @property
    def datasets(self) -> Path: return self.dir("datasets")
    @property
    def reports(self) -> Path: return self.dir("reports")
    @property
    def pbg(self) -> Path: return self.dir("pbg")
    @property
    def scripts(self) -> Path: return self.dir("scripts")
    @property
    def tests(self) -> Path: return self.dir("tests")
    @property
    def docs(self) -> Path: return self.dir("docs")
    @property
    def package(self) -> Path: return self.dir("package")

    # Study resolution (investigation-centric structure) --------------------
    def iter_study_dirs(self):
        """Yield every study dir. Top-level ``studies/<slug>/`` FIRST (so a
        top-level study wins on a slug collision and is never shadowed by a nested
        copy), then nested ``investigations/<inv>/studies/<slug>/`` for any slug
        not already yielded. A dir is a study iff it holds ``study.yaml``."""
        seen: set[str] = set()
        flat = self.dir("studies")
        if flat.is_dir():
            for s in sorted(p for p in flat.iterdir() if p.is_dir()):
                if (s / "study.yaml").is_file() and s.name not in seen:
                    seen.add(s.name)
                    yield s
        inv_root = self.dir("investigations")
        if inv_root.is_dir():
            for inv in sorted(p for p in inv_root.iterdir() if p.is_dir()):
                sroot = inv / "studies"
                if sroot.is_dir():
                    for s in sorted(p for p in sroot.iterdir() if p.is_dir()):
                        if (s / "study.yaml").is_file() and s.name not in seen:
                            seen.add(s.name)
                            yield s

    def report_dir(self, inv_slug: str) -> Path:
        """Per-investigation report/publication dir: investigations/<slug>/reports/."""
        return self.dir("investigations") / inv_slug / "reports"

    def study_dir(self, slug: str) -> Path:
        """Resolve a study by slug, nested-first then flat. Raises if absent."""
        for s in self.iter_study_dirs():
            if s.name == slug:
                return s
        raise FileNotFoundError(f"study {slug!r} not found under {self.root}")

    def inputs_dir(self, inv_slug: str) -> Path:
        """investigations/<inv_slug>/inputs (per-investigation owned inputs)."""
        return self.dir("investigations") / inv_slug / "inputs"

    def study_owner(self, slug: str):
        """Owning investigation slug for a study: nested layout, else the
        study.yaml ``investigation:`` back-ref, else the investigation whose
        forward ``studies:`` list names this study, else None.

        The forward-list fallback matters for the common flat layout
        (``studies/<slug>/``) where ownership is declared only on the
        investigation side and the study.yaml carries no back-ref."""
        try:
            d = self.study_dir(slug)
        except FileNotFoundError:
            return self._forward_study_owner(slug)
        try:
            parts = d.relative_to(self.dir("investigations")).parts
            if len(parts) >= 3 and parts[1] == "studies":
                return parts[0]
        except ValueError:
            pass
        sy = d / "study.yaml"
        if sy.is_file():
            data = yaml.safe_load(sy.read_text(encoding="utf-8")) or {}
            owner = data.get("investigation")
            if owner:
                return owner
        return self._forward_study_owner(slug)

    def _forward_study_owner(self, slug: str):
        """Scan each ``investigations/<inv>/investigation.yaml`` for one whose
        ``studies:`` list names ``slug``; return that investigation slug or None.
        Tolerates list items given as bare slugs or ``{study|slug: ...}`` dicts."""
        inv_root = self.dir("investigations")
        if not inv_root.is_dir():
            return None
        for inv_dir in sorted(inv_root.iterdir()):
            iy = inv_dir / "investigation.yaml"
            if not iy.is_file():
                continue
            try:
                data = yaml.safe_load(iy.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            for st in investigation_member_slugs(data):
                st_slug = st if isinstance(st, str) else (st or {}).get("study") or (st or {}).get("slug")
                if st_slug == slug:
                    return inv_dir.name
        return None


"""Deterministic L0-L5 reproducibility grade for studies + investigations.

Grades *how reproducible* each study/investigation is, from signals that live
entirely in this workspace (no simulation run, no build_core, no upstream
``study_audit`` dependency — so it works even when that package is absent):

  L0  Declared                  study.yaml declares a composite
  L1  Keyable                   every ``inputs[].from`` resolves → a stable
                                content-address (``artifacts.hashing.artifact_id``)
                                is well-defined for it
  L2  Run recorded              >=1 run recorded with provenance (a status; a
                                seed when the engine records one)
  L3  Content-addressed output  the artifact store holds a completed artifact
                                for this study (output is stored + pull-able)
  L4  Environment pinned        the workspace records a git commit + uv.lock
                                hash (the run is reproducible against a pinned
                                environment)
  L5  Rebuildable from sources  every transitive input producer is itself L3,
                                so the whole thing rebuilds pull-or-compute

The grade is the highest level N such that L0..LN all pass; ``blocked_by`` names
the first level that doesn't. An investigation grades as its weakest member.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import yaml

from vivarium_workbench.lib.workspace_paths import WorkspacePaths

# (level, short title, one-line meaning) — rendered verbatim in the Audit view.
LEVELS: list[tuple[int, str, str]] = [
    (0, "Declared", "spec declares a composite"),
    (1, "Keyable", "content-addressable — every input resolves"),
    (2, "Run recorded", "a run is recorded with provenance"),
    (3, "Content-addressed output", "output stored in the artifact cache"),
    (4, "Environment pinned", "git commit + lockfile recorded"),
    (5, "Rebuildable from sources", "the full input chain is content-addressed"),
]
_TERMINAL = {"completed", "complete", "passed", "success", "done", "evaluated", "ran", "ok"}


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _artifact_slugs(wp: WorkspacePaths) -> set[str]:
    """Slugs that have >=1 *completed* artifact in ``.pbg/artifacts`` (meta.json
    is written last, so its presence means the artifact is whole)."""
    base = wp.pbg / "artifacts"
    out: set[str] = set()
    if not base.is_dir():
        return out
    for d in base.iterdir():
        meta = d / "meta.json"
        if not meta.is_file():
            continue
        try:
            slug = (json.loads(meta.read_text()) or {}).get("slug")
        except (OSError, ValueError):
            slug = None
        if slug:
            out.add(str(slug))
    return out


def _has_run(ws_root: Path, slug: str) -> bool:
    """True if any run (runs.db, study.yaml ``runs:``, or runs.jsonl) is recorded
    for the study with a terminal status."""
    try:
        from vivarium_workbench.lib import study_spec
        rows = []
        for fn in ("read_runs_db_for_study", "_study_yaml_run_rows"):
            f = getattr(study_spec, fn, None)
            if f:
                try:
                    rows += f(ws_root, slug) or []
                except Exception:
                    pass
        for r in rows:
            st = str((r or {}).get("status") or "").lower()
            if st in _TERMINAL or (st and st not in {"failed", "error", "planned", "planning"}):
                return True
    except Exception:
        pass
    return False


def _study_inputs_from(spec: dict) -> list[str]:
    try:
        from vivarium_workbench.lib.study_spec import study_interface
        iface = study_interface(spec) or {}
    except Exception:
        iface = {}
    froms = []
    for inp in (iface.get("inputs") or []):
        f = (inp or {}).get("from")
        if f:
            froms.append(str(f))
    return froms


def _study_composite(spec: dict) -> str:
    """The study's baseline composite, across the several spec shapes in use:
    the canonical interface, a top-level ``baseline:`` (list-of {name,composite}
    or a dict), ``conditions.baseline``, or a bare ``composite:``."""
    try:
        from vivarium_workbench.lib.study_spec import study_interface
        c = str((study_interface(spec) or {}).get("composite") or "").strip()
        if c:
            return c
    except Exception:
        pass
    for src in (spec.get("baseline"), (spec.get("conditions") or {}).get("baseline")):
        if isinstance(src, list) and src:
            src = src[0]
        if isinstance(src, dict):
            c = str(src.get("composite") or "").strip()
            if c:
                return c
    return str(spec.get("composite") or "").strip()


def _investigation_members(inv: dict) -> list[str]:
    """Study slugs an investigation groups — supports ``members:`` and the
    ``studies:`` convention (list of strings, {study|name|slug:…} dicts, or
    single-key {slug: description} dicts; or a slug-keyed mapping)."""
    for key in ("members", "studies"):
        val = inv.get(key)
        out: list[str] = []
        if isinstance(val, list):
            for m in val:
                if isinstance(m, str):
                    out.append(m)
                elif isinstance(m, dict):
                    v = m.get("study") or m.get("name") or m.get("slug")
                    if v:
                        out.append(str(v))
                    elif len(m) == 1:
                        out.append(str(next(iter(m))))
        elif isinstance(val, dict):
            out = [str(k) for k in val]
        if out:
            return out
    return []


def _grade_from_passes(passes: list[bool]) -> tuple[int, list[dict], Optional[dict]]:
    """Return (level, checks, blocked_by). level = highest N with L0..LN all pass;
    -1 if even L0 fails."""
    checks = []
    blocked_by = None
    for (lvl, title, meaning), ok in zip(LEVELS, passes):
        checks.append({"level": f"L{lvl}", "name": title, "status": "pass" if ok else "fail",
                       "detail": meaning})
        if blocked_by is None and not ok:
            blocked_by = {"level": f"L{lvl}", "name": title}
    level = -1
    for i, ok in enumerate(passes):
        if ok:
            level = i
        else:
            break
    return level, checks, blocked_by


def _grade_label(level: int) -> str:
    return f"L{level}" if level >= 0 else "—"


class _Grader:
    def __init__(self, ws_root: Path):
        self.ws_root = Path(ws_root)
        self.wp = WorkspacePaths.load(ws_root)
        self.specs: dict[str, dict] = {}
        studies_dir = self.wp.studies
        if studies_dir.is_dir():
            for sy in sorted(studies_dir.glob("*/study.yaml")):
                self.specs[sy.parent.name] = _load_yaml(sy)
        self.existing = set(self.specs)
        self.artifact_slugs = _artifact_slugs(self.wp)
        man = {}
        try:
            from vivarium_workbench.lib.provenance_manifest import build_manifest
            man = build_manifest(ws_root) or {}
        except Exception:
            man = {}
        self.env_pinned = bool(man.get("commit")) and bool(man.get("lockfile"))
        self._grades: dict[str, dict] = {}

    def _transitive_producers(self, slug: str, seen: set[str]) -> set[str]:
        out: set[str] = set()
        for f in _study_inputs_from(self.specs.get(slug, {})):
            if f in seen:
                continue
            seen.add(f)
            out.add(f)
            out |= self._transitive_producers(f, seen)
        return out

    def study(self, slug: str) -> dict:
        if slug in self._grades:
            return self._grades[slug]
        spec = self.specs.get(slug, {})
        composite = _study_composite(spec)
        inputs_from = _study_inputs_from(spec)
        l0 = bool(composite)
        l1 = l0 and all(f in self.existing for f in inputs_from)
        l2 = l1 and _has_run(self.ws_root, slug)
        l3 = l2 and (slug in self.artifact_slugs)
        l4 = l3 and self.env_pinned
        producers = self._transitive_producers(slug, {slug})
        l5 = l4 and all(p in self.artifact_slugs for p in producers)
        level, checks, blocked = _grade_from_passes([l0, l1, l2, l3, l4, l5])
        g = {"slug": slug, "grade": {"level": level, "label": _grade_label(level),
                                     "checks": checks, "blocked_by": blocked}}
        self._grades[slug] = g
        return g

    def investigation(self, slug: str) -> dict:
        inv = _load_yaml(self.wp.investigations / slug / "investigation.yaml")
        members = _investigation_members(inv)
        member_grades = [(m, self.study(m)["grade"]["level"]) for m in members if m in self.existing]
        if member_grades:
            weakest_slug, weakest = min(member_grades, key=lambda t: t[1])
            level = weakest
            blocked = ({"level": _grade_label(weakest), "name": f"weakest member: {weakest_slug}"}
                       if weakest < 5 else None)
        else:
            level, blocked = -1, {"level": "—", "name": "no graded members"}
        return {"slug": slug,
                "grade": {"level": level, "label": _grade_label(level),
                          "n_members": len(members), "blocked_by": blocked}}


def grade_workspace(ws_root: Path | str) -> dict:
    """Grade every study + investigation. Returns
    ``{studies:{slug:grade}, investigations:{slug:grade}, distribution:{...}}``."""
    g = _Grader(Path(ws_root))
    studies = {slug: g.study(slug)["grade"] for slug in sorted(g.existing)}
    investigations: dict[str, dict] = {}
    inv_dir = g.wp.investigations
    if inv_dir.is_dir():
        for iy in sorted(inv_dir.glob("*/investigation.yaml")):
            investigations[iy.parent.name] = g.investigation(iy.parent.name)["grade"]
    dist: dict[str, int] = {}
    for grade in list(studies.values()) + list(investigations.values()):
        dist[grade["label"]] = dist.get(grade["label"], 0) + 1
    return {"studies": studies, "investigations": investigations, "distribution": dist}

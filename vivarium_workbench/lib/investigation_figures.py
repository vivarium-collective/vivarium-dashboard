"""Resolve an investigation's figures — for the Figures tab + the ``↓ figures``
download.

Two categories per member study:

* **composites** — the post-study stitched ``figure_<N>.{svg,png}`` (the "final
  figures", one per figure study). These carry a number/title/caption and drive
  the Figures tab + per-figure downloads.
* **panels** — every *other* declared image visualization on the study (loom
  SVGs, sim PNGs, gifs). These are the raw study figures.

The ``↓ figures`` zip is the **full** archive: panels *and* composites across
all member studies, organized ``<study>/<filename>``.

Figures are auto-discovered from each study's ``visualizations[]``; an optional
``figures:`` block on the investigation overrides per-figure
number/title/caption/order/inclusion:

    figures:
      - study: fig-07
        number: 7          # optional (derived from figure_<N> / slug)
        title: "…"         # optional (derived from study.title)
        caption: "…"       # optional (derived from study.claim / purpose.mechanism)
        order: 1           # optional (derived from number)
        include: true      # optional (default true; false hides an auto figure)

The resolver never raises: a missing file, unreadable study, or malformed
``figures:`` entry is skipped so the rest still resolve.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Optional

import yaml

from vivarium_workbench.lib.investigation_members import investigation_member_slugs
from vivarium_workbench.lib.study_charts import _FIGURE_ADDR_SCHEMES, _resolve_figure_path
from vivarium_workbench.lib.workspace_paths import WorkspacePaths, study_dir

# ``figure_7`` / ``figure-7`` → 7. The stitcher writes ``figure_<N>.svg``.
_COMPOSITE_RE = re.compile(r"figure[_-](\d+)$", re.IGNORECASE)
# ``fig-07`` / ``fig07`` → 7 (fallback figure number from the study slug).
_SLUG_NUM_RE = re.compile(r"fig[-_]?0*(\d+)", re.IGNORECASE)


def _load_investigation(ws_root: Path, name: str) -> Optional[dict]:
    f = WorkspacePaths.load(ws_root).investigations / name / "investigation.yaml"
    if not f.is_file():
        return None
    try:
        return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except Exception:
        return None


def _load_study(ws_root: Path, slug: str) -> tuple[Optional[Path], dict]:
    try:
        sdir = study_dir(ws_root, slug, must_exist=True)
    except Exception:
        return None, {}
    try:
        spec = yaml.safe_load((sdir / "study.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        spec = {}
    return sdir, spec


def _image_files(study_dir_path: Path, spec: dict) -> list[Path]:
    """Every declared image-figure file on a study (svg/png/gif/jpg), in the
    order the study declares them. Deduped, existing files only."""
    out: list[Path] = []
    seen: set[Path] = set()
    for entry in (spec.get("visualizations") or []):
        if not isinstance(entry, dict):
            continue
        addr = str(entry.get("address") or "").strip()
        if ":" not in addr:
            continue
        scheme, _, rest = addr.partition(":")
        if scheme.strip().lower() not in _FIGURE_ADDR_SCHEMES:
            continue
        p = _resolve_figure_path(study_dir_path, rest.strip())
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _caption_for(spec: dict) -> str:
    claim = str(spec.get("claim") or "").strip()
    if claim:
        return claim
    mech = ((spec.get("purpose") or {}).get("mechanism")) if isinstance(spec.get("purpose"), dict) else ""
    return " ".join(str(mech or "").split())


def build_investigation_figures(ws_root, name: str) -> dict:
    """Resolve ``name``'s figures.

    Returns::

        {
          "composites": [ {study, number, title, caption, order,
                           svg_rel, png_rel|None}, … ],   # ordered
          "files":      [ {study, arcname, rel_path}, … ], # EVERY figure file
          "n_composites": int,
        }

    ``*_rel`` paths are workspace-root-relative POSIX strings; the API/publish
    layers turn them into live vs snapshot URLs.
    """
    ws_root = Path(ws_root).resolve()  # absolute → relative_to(ws_root) is safe when callers pass '.'
    inv = _load_investigation(ws_root, name) or {}
    slugs = investigation_member_slugs(inv)

    overrides: dict[str, dict] = {}
    for f in (inv.get("figures") or []):
        if isinstance(f, dict) and f.get("study"):
            overrides[str(f["study"])] = f

    composites: list[dict] = []
    files: list[dict] = []
    for slug in slugs:
        ov = overrides.get(slug, {})
        if ov.get("include") is False:
            continue
        sdir, spec = _load_study(ws_root, slug)
        if sdir is None:
            continue
        imgs = _image_files(sdir, spec)
        for p in imgs:
            try:
                rel = p.relative_to(ws_root).as_posix()
            except ValueError:
                continue
            files.append({"study": slug, "arcname": f"{slug}/{p.name}", "rel_path": rel})

        # Composite(s): figure_<N>.svg (the post-study stitched figure).
        slug_num = _SLUG_NUM_RE.match(slug)
        for csvg in imgs:
            m = _COMPOSITE_RE.match(csvg.stem)
            if not m or csvg.suffix.lower() != ".svg":
                continue
            number = ov.get("number") or int(m.group(1) if m else (slug_num.group(1) if slug_num else 0))
            png = csvg.with_suffix(".png")
            try:
                svg_rel = csvg.relative_to(ws_root).as_posix()
                png_rel = png.relative_to(ws_root).as_posix() if png.exists() else None
            except ValueError:
                continue
            composites.append({
                "study": slug,
                "number": number,
                "title": str(ov.get("title") or spec.get("title") or slug),
                "caption": str(ov.get("caption") or _caption_for(spec)),
                "order": ov.get("order", number),
                "svg_rel": svg_rel,
                "png_rel": png_rel,
            })

    composites.sort(key=lambda c: (c["order"], c["number"]))
    return {"composites": composites, "files": files, "n_composites": len(composites)}


_EXT_MIME = {"svg": "image/svg+xml", "png": "image/png"}


def resolve_figure_file(ws_root, name: str, number: int, ext: str) -> Optional[Path]:
    """The composite figure file for ``Figure <number>`` in ``.<ext>`` (svg|png),
    or ``None``. Backs ``GET /api/investigation/<slug>/figure/<n>.<ext>``."""
    ext = ext.lower().lstrip(".")
    if ext not in _EXT_MIME:
        return None
    ws_root = Path(ws_root).resolve()  # absolute → relative_to(ws_root) is safe when callers pass '.'
    for c in build_investigation_figures(ws_root, name)["composites"]:
        if int(c["number"]) != int(number):
            continue
        rel = c["svg_rel"] if ext == "svg" else c.get("png_rel")
        if not rel:
            return None
        p = ws_root / rel
        return p if p.is_file() else None
    return None


def build_figures_zip(ws_root, name: str) -> Optional[bytes]:
    """Zip EVERY figure file (panels + composites) across the investigation's
    member studies, arranged ``<study>/<filename>``. Returns ``None`` when the
    investigation has no figure files. Backs
    ``GET /api/investigation/<slug>/figures.zip``."""
    ws_root = Path(ws_root).resolve()  # absolute → relative_to(ws_root) is safe when callers pass '.'
    figs = build_investigation_figures(ws_root, name)
    entries = figs["files"]
    if not entries:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen: set[str] = set()
        for e in entries:
            src = ws_root / e["rel_path"]
            arc = e["arcname"]
            if arc in seen or not src.is_file():
                continue
            seen.add(arc)
            try:
                zf.write(src, arc)
            except OSError:
                continue
    return buf.getvalue()


def study_figure_files(ws_root, slug: str) -> list[Path]:
    """Every declared image-figure file on a single study (panels + its own
    composite). Backs the study-scoped ``↓ figures``."""
    ws_root = Path(ws_root).resolve()  # absolute → relative_to(ws_root) is safe when callers pass '.'
    sdir, spec = _load_study(ws_root, slug)
    if sdir is None:
        return []
    return _image_files(sdir, spec)


def build_study_figures_zip(ws_root, slug: str) -> Optional[bytes]:
    """Zip a single study's figures (flat, ``<filename>``), or ``None`` when the
    study has none. Backs ``GET /api/study/<slug>/figures.zip``."""
    imgs = study_figure_files(ws_root, slug)
    if not imgs:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen: set[str] = set()
        for p in imgs:
            if p.name in seen or not p.is_file():
                continue
            seen.add(p.name)
            try:
                zf.write(p, p.name)
            except OSError:
                continue
    return buf.getvalue()

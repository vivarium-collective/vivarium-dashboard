"""The visualization readiness gate (Fable §5(A)/§6(c), Task V4).

Single source of truth for "does this study have a *qualifying*
visualization?" — probed WITHOUT re-rendering, by reusing the three existing
figure-source payload builders:

  * ``study_native_gallery.build_study_native_gallery``  — native (Altair/
    Plotly srcdoc) panels from the study's latest completed run's
    ``viz.json``.
  * ``study_charts.build_study_charts_payload``           — live inline-SVG
    charts (from ``runs.db``) + static charts (``charts/*.svg|png|gif`` and
    declared ``visualizations:`` figures resolved to static images).
  * ``study_spec.discover_viz_html_files`` + the study's own
    ``embed_visualizations:`` declaration — embedded Plotly/JS HTML pages.

A study's visualizations **qualify** iff BOTH hold (the two conditions may be
satisfied by *different* figures):

  * ``has_interactive`` — at least one figure of an *interactive* kind
    (embedded HTML, a native-gallery panel, a ``.gif``, or a future
    ``threejs``/``html`` declared figure — see ``_INTERACTIVE_KINDS`` below,
    the single place V6 (three.js) extends this set).
  * ``has_run_linked``  — at least one figure carries a real (non-null)
    ``run_id`` — genuine run provenance, threaded through by Task V3.

A lone static image (``.svg``/``.png``) never satisfies ``has_interactive``,
no matter how many of them exist.

Cheap by construction: every probe below reuses an EXISTING payload builder
(no forked figure-discovery, no full zarr open, no re-rendering) and is
individually wrapped so a study whose composite/runs can't be read degrades
to "no figures found from that source" instead of raising — mirroring how
``report_views._iter_study_slugs`` tolerates an unparseable ``study.yaml``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# The interactive-set — encoded ONCE so future figure kinds (V6: three.js)
# just need to tag their records with one of these kind strings to qualify.
# ---------------------------------------------------------------------------
_INTERACTIVE_KINDS = frozenset({
    "html",     # embed_visualizations (Plotly/JS pages, studies/<slug>/viz/*.html)
    "native",   # native-gallery panels (Altair/Plotly srcdoc)
    "gif",      # animated raster charts
    "threejs",  # (future, V6) declared threejs: figures
})

# Kinds that are explicitly static — never satisfy has_interactive even if a
# future source starts stamping them with a run_id.
_STATIC_KINDS = frozenset({"svg", "png"})


def _read_study_spec(ws_root: Path, slug: str) -> dict:
    """Best-effort raw ``study.yaml`` read, tolerant like ``_iter_study_slugs``.

    Returns ``{}`` for any structural failure (missing workspace, missing/
    unparseable study.yaml, non-dict YAML) — never raises.
    """
    try:
        from vivarium_workbench.lib.workspace_paths import WorkspacePaths
        wp = WorkspacePaths.load(ws_root)
        study_dir = wp.study_dir(slug)
    except Exception:  # noqa: BLE001
        study_dir = Path(ws_root) / "studies" / slug
    f = study_dir / "study.yaml"
    if not f.is_file():
        return {}
    try:
        spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}
    return spec if isinstance(spec, dict) else {}


def study_visualization_status(ws_root: Path, slug: str) -> dict:
    """Probe the three figure sources and apply the quality bar.

    Returns::

        {
          "has_interactive": bool,
          "has_run_linked":  bool,
          "has_runs":        bool,        # Task Vcal
          "qualifies":       bool,
          "n_figures":       int,
          "reason":          str | None,  # why qualifies is False
          "gap_severity":    str | None,  # Task Vcal: "warning" | "info" | None
        }

    ``reason`` (most-informative-first when multiple apply):
      "no figures" > "no interactive figure (only static images)"
                   > "no figure linked to a run"
    ``None`` when ``qualifies`` is True.

    ``gap_severity`` (Task Vcal — recalibrates the V4 bar so an unrun study
    isn't scolded just for not having been executed yet):
      * ``"warning"`` — NOT ``has_interactive`` (no figures, or static-only).
        The genuine "empty/boring study" problem; downgrades the Evidence
        gate (V5).
      * ``"info"``    — ``has_interactive`` AND NOT ``has_run_linked`` AND
        the study HAS >=1 recorded run. A soft provenance nudge; never
        downgrades Evidence.
      * ``None``      — either fully qualifying, OR the not-run-linked case
        for a study with NO recorded runs at all (silent — an unrun study
        isn't a visualization problem).
    """
    ws_root = Path(ws_root)
    n_figures = 0
    has_interactive = False
    has_run_linked = False

    def _mark(kind: Optional[str], run_id: Any) -> None:
        nonlocal n_figures, has_interactive, has_run_linked
        n_figures += 1
        if kind in _INTERACTIVE_KINDS:
            has_interactive = True
        if run_id:
            has_run_linked = True

    # Source 1: native gallery panels (Altair/Plotly srcdoc) from the study's
    # latest completed run's viz.json. Every panel shares that run's run_id.
    try:
        from vivarium_workbench.lib.study_native_gallery import build_study_native_gallery
        gallery = build_study_native_gallery(ws_root, slug)
    except Exception:  # noqa: BLE001 — unreadable study: no native figures
        gallery = {"run_id": None, "panels": {}}
    gallery_run_id = (gallery or {}).get("run_id")
    for _panel_html in ((gallery or {}).get("panels") or {}).values():
        _mark("native", gallery_run_id)

    # Source 2: live inline-SVG charts (runs.db) + static charts (charts/*
    # and declared `visualizations:` figures resolved to static images).
    try:
        from vivarium_workbench.lib.study_charts import build_study_charts_payload
        charts_payload = build_study_charts_payload(ws_root, slug)
    except Exception:  # noqa: BLE001 — unreadable study: no chart figures
        charts_payload = {"charts": []}
    for c in (charts_payload or {}).get("charts") or []:
        if not isinstance(c, dict):
            continue
        media = (c.get("media") or "").strip().lower()
        # Live charts (render_study_charts / render_v4_test_charts) carry no
        # `media` field but do carry an inline `svg` — they're still a static
        # SVG figure for the purposes of the bar.
        kind = media or ("svg" if c.get("svg") else None)
        _mark(kind, c.get("run_id"))

    # Source 3: embedded HTML figures — auto-discovered (studies/<slug>/viz/
    # *.html, reports/figures/<slug>/*.html) merged with any manually
    # declared `embed_visualizations:` entries not already covered by
    # auto-discovery (deduped by url).
    embeds: list[dict] = []
    try:
        from vivarium_workbench.lib.study_spec import discover_viz_html_files
        embeds.extend(discover_viz_html_files(ws_root, slug))
    except Exception:  # noqa: BLE001 — unreadable study: no auto-discovered embeds
        pass
    spec = _read_study_spec(ws_root, slug)
    seen_urls = {e.get("url") for e in embeds if isinstance(e, dict)}
    for e in (spec.get("embed_visualizations") or []):
        if isinstance(e, dict) and e.get("url") not in seen_urls:
            embeds.append(e)
            seen_urls.add(e.get("url"))
    for e in embeds:
        if not isinstance(e, dict):
            continue
        _mark("html", e.get("run_id"))

    # Source 4 (Task V6): declared `visualizations:` entries using a
    # threejs:/html: address scheme. As of V6, `discover_declared_figure_
    # charts` (Source 2, via `build_study_charts_payload`) also resolves
    # these — but only when the referenced file exists on disk. This source
    # reads the raw spec directly (no file-existence check), so an entry
    # whose figure file hasn't landed yet still counts toward
    # `has_interactive` (matching how the OTHER interactive sources here
    # tolerate not-yet-materialized state) rather than silently vanishing
    # from the gate. Harmlessly redundant with Source 2 when the file does
    # exist (`_mark` just re-marks the same kind).
    for v in (spec.get("visualizations") or []):
        if not isinstance(v, dict):
            continue
        addr = str(v.get("address") or "")
        scheme = addr.split(":", 1)[0].strip().lower() if ":" in addr else ""
        if scheme in ("threejs", "html"):
            _mark(scheme, v.get("run_id"))

    if n_figures == 0:
        reason = "no figures"
    elif not has_interactive:
        reason = "no interactive figure (only static images)"
    elif not has_run_linked:
        reason = "no figure linked to a run"
    else:
        reason = None

    # Task Vcal: "has this study been run at all?" — reuses the existing
    # `read_runs_db_for_study` call (the same one `build_study_native_gallery`
    # already calls internally) rather than a new scan. Tolerant: an
    # unreadable runs.db/study.yaml reads as "no runs", never raises.
    has_runs = False
    try:
        from vivarium_workbench.lib.study_spec import read_runs_db_for_study
        has_runs = bool(read_runs_db_for_study(ws_root, slug))
    except Exception:  # noqa: BLE001
        has_runs = False

    if not has_interactive:
        gap_severity: Optional[str] = "warning"
    elif not has_run_linked:
        gap_severity = "info" if has_runs else None
    else:
        gap_severity = None

    return {
        "has_interactive": has_interactive,
        "has_run_linked": has_run_linked,
        "has_runs": has_runs,
        "qualifies": has_interactive and has_run_linked,
        "n_figures": n_figures,
        "reason": reason,
        "gap_severity": gap_severity,
    }

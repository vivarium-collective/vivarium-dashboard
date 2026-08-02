"""Task V4 — the visualization readiness gate.

``study_visualization_status`` probes the three existing figure-source
payload builders (native gallery, static/inline charts, embed HTML) WITHOUT
re-rendering and applies the explicit quality bar: qualifies iff >=1
interactive figure AND >=1 figure linked to a real run_id. These tests
monkeypatch the three source probes (as the brief calls out) so each of the
five status combinations is exercised in isolation, independent of any real
fixture workspace's run history.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from vivarium_workbench.lib import viz_gate


def _patch_sources(monkeypatch, *, gallery=None, charts=None, embeds=None):
    """Patch the three probes at their SOURCE module (viz_gate imports them
    lazily inside the function body, so patching the source attribute is
    what actually takes effect on the next call)."""
    import vivarium_workbench.lib.study_native_gallery as _gallery_mod
    import vivarium_workbench.lib.study_charts as _charts_mod
    import vivarium_workbench.lib.study_spec as _spec_mod

    monkeypatch.setattr(
        _gallery_mod, "build_study_native_gallery",
        lambda ws_root, slug: gallery if gallery is not None else {"run_id": None, "panels": {}},
    )
    monkeypatch.setattr(
        _charts_mod, "build_study_charts_payload",
        lambda ws_root, slug, **kw: charts if charts is not None else {"charts": []},
    )
    monkeypatch.setattr(
        _spec_mod, "discover_viz_html_files",
        lambda ws_root, slug: embeds if embeds is not None else [],
    )


def _empty_study(tmp_path) -> Path:
    ws = tmp_path / "ws"
    sd = ws / "studies" / "s1"
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text("name: s1\n", encoding="utf-8")
    return ws


def _patch_runs(monkeypatch, runs: list[dict]) -> None:
    """Patch ``has_runs``'s data source (Task Vcal): ``viz_gate`` imports
    ``read_runs_db_for_study`` lazily inside the function body, same pattern
    as ``_patch_sources`` above, so patch the source attribute."""
    import vivarium_workbench.lib.study_spec as _spec_mod

    monkeypatch.setattr(
        _spec_mod, "read_runs_db_for_study",
        lambda ws_root, name: list(runs),
    )


# ---------------------------------------------------------------------------
# (i) embed HTML linked to a run -> qualifies
# ---------------------------------------------------------------------------

def test_embed_html_linked_to_run_qualifies(tmp_path, monkeypatch):
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        embeds=[{"name": "plot", "url": "/studies/s1/viz/plot.html", "run_id": "run-1"}],
    )
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["qualifies"] is True
    assert status["has_interactive"] is True
    assert status["has_run_linked"] is True
    assert status["reason"] is None
    assert status["n_figures"] == 1


# ---------------------------------------------------------------------------
# (ii) only a static .svg -> not qualifies, reason "no interactive figure"
# ---------------------------------------------------------------------------

def test_only_static_svg_does_not_qualify(tmp_path, monkeypatch):
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        charts={"charts": [
            {"key": "mass", "media": "svg", "svg": "<svg/>", "run_id": "run-1"},
        ]},
    )
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["qualifies"] is False
    assert status["has_interactive"] is False
    assert status["has_run_linked"] is True
    assert status["reason"] == "no interactive figure (only static images)"


# ---------------------------------------------------------------------------
# (iii) interactive figure but no run_id anywhere -> not qualifies, reason
#       "no figure linked to a run"
# ---------------------------------------------------------------------------

def test_interactive_without_run_id_does_not_qualify(tmp_path, monkeypatch):
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        embeds=[{"name": "plot", "url": "/reports/figures/s1/plot.html", "run_id": None}],
    )
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["qualifies"] is False
    assert status["has_interactive"] is True
    assert status["has_run_linked"] is False
    assert status["reason"] == "no figure linked to a run"


# ---------------------------------------------------------------------------
# (iv) zero figures -> not qualifies, reason "no figures"
# ---------------------------------------------------------------------------

def test_zero_figures_does_not_qualify(tmp_path, monkeypatch):
    ws = _empty_study(tmp_path)
    _patch_sources(monkeypatch)
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["qualifies"] is False
    assert status["n_figures"] == 0
    assert status["reason"] == "no figures"


# ---------------------------------------------------------------------------
# (v) a .gif linked to a run -> qualifies
# ---------------------------------------------------------------------------

def test_gif_linked_to_run_qualifies(tmp_path, monkeypatch):
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        charts={"charts": [
            {"key": "colony", "media": "gif", "img": "data:image/gif;base64,AAAA", "run_id": "run-7"},
        ]},
    )
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["qualifies"] is True
    assert status["reason"] is None


# ---------------------------------------------------------------------------
# Review fix round 1: `_embed_gif_chart` (study_charts.py, the perf-sweep
# colony-animation chart) puts its GIF <img> tag in the `svg` field with no
# `media` key of its own — before the fix, viz_gate's `("svg" if c.get("svg")
# else None)` fallback misclassified that as a STATIC svg figure, defeating
# has_interactive for a genuinely-animated GIF. Exercise the function's REAL
# output shape (not a synthetic dict) to guard the fix at the integration
# point, and pin the companion guard: a real static .svg chart (no `media`
# key, just an inline `svg` field) must still classify as static — the fix
# must not flip svg-field charts to interactive wholesale.
# ---------------------------------------------------------------------------

def test_embed_gif_chart_shape_classifies_as_interactive(tmp_path, monkeypatch):
    from vivarium_workbench.lib.study_charts import _embed_gif_chart

    gif_path = tmp_path / "colony.gif"
    gif_path.write_bytes(b"GIF89aFAKE")
    gif_chart = _embed_gif_chart(gif_path, key="colony-animation",
                                 title="Colony growth", caption="...")
    assert gif_chart is not None
    assert gif_chart["media"] == "gif"  # the fix: explicit type marker
    assert "svg" in gif_chart  # additive: the renderer still gets its <img> markup
    gif_chart["run_id"] = "run-7"  # simulate provenance for the qualifying case

    ws = _empty_study(tmp_path)
    _patch_sources(monkeypatch, charts={"charts": [gif_chart]})
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["has_interactive"] is True
    assert status["qualifies"] is True


def test_real_static_svg_chart_still_classifies_as_static(tmp_path, monkeypatch):
    """Guard: a genuine static SVG chart (svg field, no media key — the same
    shape live/v4-test charts use) must NOT be flipped to interactive by the
    gif-classification fix."""
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        charts={"charts": [
            {"key": "mass", "svg": "<svg><rect/></svg>", "run_id": "run-1"},
        ]},
    )
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["has_interactive"] is False
    assert status["qualifies"] is False
    assert status["reason"] == "no interactive figure (only static images)"


# ---------------------------------------------------------------------------
# Native gallery panels are interactive and share the gallery's run_id.
# ---------------------------------------------------------------------------

def test_native_gallery_panel_with_run_id_qualifies(tmp_path, monkeypatch):
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        gallery={"run_id": "run-9", "panels": {"mass_fraction": "<div>plotly</div>"}},
    )
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["qualifies"] is True


# ---------------------------------------------------------------------------
# Mixed sources: a static chart + a run-linked interactive figure in
# DIFFERENT figures both satisfy the bar (the two conditions need not be the
# same figure).
# ---------------------------------------------------------------------------

def test_bar_satisfied_by_different_figures(tmp_path, monkeypatch):
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        charts={"charts": [
            {"key": "mass", "media": "svg", "svg": "<svg/>", "run_id": "run-1"},
        ]},
        embeds=[{"name": "plot", "url": "/x.html", "run_id": None}],
        gallery={"run_id": "run-3", "panels": {}},
    )
    # has_interactive comes from the embed HTML; has_run_linked comes from
    # the (non-interactive) static svg's run_id — different figures, but the
    # bar only requires each condition to hold SOMEWHERE, so this qualifies.
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["has_run_linked"] is True  # from the static svg's run_id
    assert status["has_interactive"] is True  # from the embed html
    assert status["qualifies"] is True
    assert status["reason"] is None


# ---------------------------------------------------------------------------
# Tolerant of a study whose composite/runs can't be read (no 500 / no raise).
# ---------------------------------------------------------------------------

def test_unreadable_sources_do_not_raise(tmp_path, monkeypatch):
    ws = _empty_study(tmp_path)

    def _boom(*a, **kw):
        raise RuntimeError("composite cannot be resolved")

    import vivarium_workbench.lib.study_native_gallery as _gallery_mod
    import vivarium_workbench.lib.study_charts as _charts_mod
    import vivarium_workbench.lib.study_spec as _spec_mod

    monkeypatch.setattr(_gallery_mod, "build_study_native_gallery", _boom)
    monkeypatch.setattr(_charts_mod, "build_study_charts_payload", _boom)
    monkeypatch.setattr(_spec_mod, "discover_viz_html_files", _boom)

    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["qualifies"] is False
    assert status["n_figures"] == 0
    assert status["reason"] == "no figures"


def test_unreadable_study_yaml_does_not_raise(tmp_path, monkeypatch):
    """A study whose study.yaml is missing/unparseable still returns a
    tolerant, not-qualifying status rather than raising."""
    ws = tmp_path / "ws"
    (ws / "studies").mkdir(parents=True)
    status = viz_gate.study_visualization_status(ws, "does-not-exist")
    assert status["qualifies"] is False
    assert status["n_figures"] == 0


# ---------------------------------------------------------------------------
# Task Vcal — recalibrate the visualization gap into three outcomes via a new
# `gap_severity` field, driven by a new `has_runs` signal. Kills the 56/56
# noise: a study that was never RUN can't satisfy "run-linked" and shouldn't
# be scolded for it (silent), but a genuinely empty/boring study (no
# interactive figure) still warns, and a run study that just hasn't linked
# provenance yet gets a soft info nudge.
# ---------------------------------------------------------------------------

def test_vcal_case_a_static_only_gap_severity_warning(tmp_path, monkeypatch):
    """(a) static-only study -> gap_severity == 'warning' regardless of
    has_runs (the no-interactive case is the genuine empty/boring problem)."""
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        charts={"charts": [
            {"key": "mass", "media": "svg", "svg": "<svg/>", "run_id": "run-1"},
        ]},
    )
    _patch_runs(monkeypatch, [{"run_id": "run-1", "status": "completed"}])
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["has_interactive"] is False
    assert status["gap_severity"] == "warning"


def test_vcal_case_b_interactive_no_run_link_has_runs_gap_severity_info(tmp_path, monkeypatch):
    """(b) interactive + no run-linked + HAS >=1 recorded run ->
    gap_severity == 'info' (soft provenance nudge, not a hard warning)."""
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        embeds=[{"name": "plot", "url": "/x.html", "run_id": None}],
    )
    _patch_runs(monkeypatch, [{"run_id": "run-1", "status": "completed"}])
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["has_interactive"] is True
    assert status["has_run_linked"] is False
    assert status["has_runs"] is True
    assert status["gap_severity"] == "info"


def test_vcal_case_c_interactive_no_run_link_no_runs_gap_severity_none(tmp_path, monkeypatch):
    """(c) interactive + no run-linked + NO recorded runs at all ->
    gap_severity is None (silent — an unrun study isn't a viz problem, this
    is exactly the 37-noise-case fix)."""
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        embeds=[{"name": "plot", "url": "/x.html", "run_id": None}],
    )
    _patch_runs(monkeypatch, [])
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["has_interactive"] is True
    assert status["has_run_linked"] is False
    assert status["has_runs"] is False
    assert status["gap_severity"] is None


def test_vcal_case_d_fully_qualifying_gap_severity_none(tmp_path, monkeypatch):
    """(d) fully qualifying (interactive + run-linked) -> gap_severity is
    None, whether or not other runs are on record."""
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        embeds=[{"name": "plot", "url": "/x.html", "run_id": "run-1"}],
    )
    _patch_runs(monkeypatch, [{"run_id": "run-1", "status": "completed"}])
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["qualifies"] is True
    assert status["gap_severity"] is None


def test_vcal_case_e_empty_study_gap_severity_warning(tmp_path, monkeypatch):
    """(e) empty study (zero figures) -> gap_severity == 'warning', even
    with zero recorded runs (no-interactive always wins over has_runs)."""
    ws = _empty_study(tmp_path)
    _patch_sources(monkeypatch)
    _patch_runs(monkeypatch, [])
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["n_figures"] == 0
    assert status["gap_severity"] == "warning"


def test_vcal_has_runs_default_derivation_reads_runs_db(tmp_path, monkeypatch):
    """Without patching has_runs's own source, `has_runs` is derived from
    the real (empty, since no runs.db/study.yaml runs: exist)
    `read_runs_db_for_study` — proving the field is actually wired to a real
    signal, not hardcoded."""
    ws = _empty_study(tmp_path)
    _patch_sources(
        monkeypatch,
        embeds=[{"name": "plot", "url": "/x.html", "run_id": None}],
    )
    status = viz_gate.study_visualization_status(ws, "s1")
    assert status["has_runs"] is False
    assert status["gap_severity"] is None

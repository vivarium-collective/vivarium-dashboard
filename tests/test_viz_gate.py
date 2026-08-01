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

"""A rich report card embedded in Visualizations belongs on the Report Cards tab.

`_promote_report_card_embeds` moves a `docs/report_cards/<set>/<card>/report_card.html`
embed into `report_card_urls` (preferring its rich render + its own verdict) and
drops it from `embed_visualizations` so Visualizations shows real figures.
"""
from __future__ import annotations

import json
from pathlib import Path

from vivarium_workbench.lib.study_spec import (
    _is_report_card_embed,
    _promote_report_card_embeds,
)


def test_detects_report_card_embeds():
    assert _is_report_card_embed(
        {"url": "/docs/report_cards/pop_basal/vs_vecoli/report_card.html"})
    assert _is_report_card_embed({"name": "v1↔v2 equivalence report card", "url": "/x.html"})
    # A real figure is NOT a report card.
    assert not _is_report_card_embed(
        {"name": "Units Atlas", "url": "/reports/figures/s/units_atlas.html"})


def _write_rich_bundle(ws: Path, overall: str) -> str:
    d = ws / "docs" / "report_cards" / "pop_basal" / "vs_vecoli"
    d.mkdir(parents=True)
    (d / "report_card.html").write_text("<html>rich 16x16 card</html>" * 500)
    (d / "report_card_verdict.json").write_text(json.dumps(
        {"overall": overall, "groups": {"physiology": {"axes": []}}}))
    return "/docs/report_cards/pop_basal/vs_vecoli/report_card.html"


def test_promotes_rich_card_and_drops_embed(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    url = _write_rich_bundle(ws, "mismatch")
    spec = {
        # thin/stale card already discovered from viz/report_card + a wrong verdict
        "report_card_urls": {"vs_vecoli": {"url": "/viz/report_card/vs_vecoli.html",
                                           "verdict": "within_tol", "html_stub": False}},
        "embed_visualizations": [
            {"name": "v1↔v2 equivalence report card (16×16)", "url": url},
            {"name": "Units Atlas (interactive)", "url": "/reports/figures/s/units_atlas.html"},
        ],
    }
    _promote_report_card_embeds(spec, ws)

    # Report Cards tab: the rich render + the rich verdict win.
    rc = spec["report_card_urls"]["vs_vecoli"]
    assert rc["url"] == url
    assert rc["verdict"] == "mismatch"       # not the stale within_tol
    assert rc["rich"] is True

    # Visualizations: the card embed is gone; the real figure remains.
    names = [e["name"] for e in spec["embed_visualizations"]]
    assert names == ["Units Atlas (interactive)"]


def test_no_report_card_embed_is_a_noop(tmp_path):
    spec = {
        "report_card_urls": {"c": {"url": "/viz/report_card/c.html"}},
        "embed_visualizations": [{"name": "chart", "url": "/reports/figures/s/x.html"}],
    }
    _promote_report_card_embeds(spec, tmp_path)
    assert len(spec["embed_visualizations"]) == 1
    assert spec["report_card_urls"]["c"]["url"] == "/viz/report_card/c.html"


# --- Content-aware detection: a report card hand-dropped into reports/figures/
# under a figure-style filename must still be classified as a report card, so
# the misclassification does not depend on where the file lives or its name. ---

def _write_html(ws: Path, rel: str, body: str) -> str:
    p = ws / rel.lstrip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return "/" + rel.lstrip("/")


def test_detects_hand_authored_card_by_marker(tmp_path):
    ws = tmp_path / "ws"
    url = _write_html(ws, "reports/figures/s/1-fba-bridge.html",
                      '<html><head><meta name="viv-artifact" content="report-card">'
                      '<title>anything at all</title></head><body>…</body></html>')
    # Figure-style name + figures/ location: heuristics alone miss it...
    assert not _is_report_card_embed({"name": "1-fba-bridge", "url": url})
    # ...but with ws_root the content marker deterministically catches it.
    assert _is_report_card_embed({"name": "1-fba-bridge", "url": url}, ws)


def test_detects_hand_authored_card_by_title(tmp_path):
    ws = tmp_path / "ws"
    url = _write_html(ws, "reports/figures/s/1-fba-bridge.html",
                      "<html><head><title>v2ecoli vs Millard — central-carbon "
                      "exchange — report card</title></head><body>…</body></html>")
    assert _is_report_card_embed({"name": "1-fba-bridge", "url": url}, ws)


def test_real_figure_by_content_is_not_a_report_card(tmp_path):
    ws = tmp_path / "ws"
    url = _write_html(ws, "reports/figures/s/5-nadh.html",
                      "<html><head><title>KETCHUP FDH dynamic fit — NADH(t)</title>"
                      "</head><body>plot</body></html>")
    assert not _is_report_card_embed({"name": "5-nadh", "url": url}, ws)


def test_promotes_multiple_figures_dir_cards_keyed_by_stem(tmp_path):
    """Two report cards in the same figures/<study>/ dir promote under DISTINCT
    stem keys (not colliding on the study dir), and a real figure stays."""
    ws = tmp_path / "ws"
    card1 = _write_html(ws, "reports/figures/ketchup/1-fba-bridge.html",
                        "<title>A — report card</title>")
    card2 = _write_html(ws, "reports/figures/ketchup/2-ecoli307.html",
                        "<title>B — report card</title>")
    fig = _write_html(ws, "reports/figures/ketchup/5-nadh.html",
                      "<title>NADH(t)</title>")
    spec = {
        "embed_visualizations": [
            {"name": "1-fba-bridge", "url": card1},
            {"name": "2-ecoli307", "url": card2},
            {"name": "5-nadh", "url": fig},
        ],
    }
    _promote_report_card_embeds(spec, ws)
    # Both cards promoted under their own stem — no collision, both survive.
    assert set(spec["report_card_urls"]) == {"1-fba-bridge", "2-ecoli307"}
    assert spec["report_card_urls"]["1-fba-bridge"]["url"] == card1
    assert spec["report_card_urls"]["2-ecoli307"]["url"] == card2
    # The real figure remains on Visualizations.
    assert [e["name"] for e in spec["embed_visualizations"]] == ["5-nadh"]

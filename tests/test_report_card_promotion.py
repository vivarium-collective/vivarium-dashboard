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

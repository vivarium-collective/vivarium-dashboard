"""Task V6 — declared `threejs:`/`html:` self-contained-HTML figures.

End-to-end (not monkeypatched): a study declares a `visualizations:` entry
pointing at a self-contained HTML file via `threejs:`/`html:`. It must:

  * resolve through `study_charts.build_study_charts_payload` to a chart
    record with the interactive `media` marker and an `iframe_url` (no
    img/svg payload — it renders as an iframe, not a static image);
  * make `viz_gate.study_visualization_status` report `has_interactive is
    True` for a study whose ONLY figure is that declared figure.

Also pins the no-regression requirement: the existing static schemes
(`png:`/`svg:`) still resolve to a static image record and do NOT flip
`has_interactive`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib import viz_gate
from vivarium_workbench.lib.study_charts import build_study_charts_payload


def _build_study(tmp_path: Path, *, address: str, fig_name: str, fig_bytes_or_text) -> tuple[Path, str]:
    ws = tmp_path / "ws"
    study_dir = ws / "studies" / "demo"
    study_dir.mkdir(parents=True)
    fig_path = study_dir / fig_name
    if isinstance(fig_bytes_or_text, bytes):
        fig_path.write_bytes(fig_bytes_or_text)
    else:
        fig_path.write_text(fig_bytes_or_text, encoding="utf-8")
    (study_dir / "study.yaml").write_text(
        yaml.safe_dump({
            "name": "demo",
            "visualizations": [{"name": "fig", "address": address}],
        }),
        encoding="utf-8",
    )
    return ws, "demo"


def test_threejs_declared_figure_is_interactive_end_to_end(tmp_path):
    ws, name = _build_study(
        tmp_path, address="threejs:scene.html", fig_name="scene.html",
        fig_bytes_or_text="<html><body>3D scene</body></html>",
    )
    payload = build_study_charts_payload(ws, name)
    [rec] = [c for c in payload["charts"] if c.get("source") == "declared"]
    assert rec["media"] == "threejs"
    assert rec["iframe_url"] == "/studies/demo/scene.html"
    assert "img" not in rec
    assert "svg" not in rec

    status = viz_gate.study_visualization_status(ws, name)
    assert status["has_interactive"] is True
    assert status["n_figures"] >= 1


def test_html_declared_figure_is_interactive_end_to_end(tmp_path):
    ws, name = _build_study(
        tmp_path, address="html:page.html", fig_name="page.html",
        fig_bytes_or_text="<html><body>self-contained</body></html>",
    )
    payload = build_study_charts_payload(ws, name)
    [rec] = [c for c in payload["charts"] if c.get("source") == "declared"]
    assert rec["media"] == "html"
    assert rec["iframe_url"] == "/studies/demo/page.html"

    status = viz_gate.study_visualization_status(ws, name)
    assert status["has_interactive"] is True


def test_declared_png_figure_still_static_no_regression(tmp_path):
    ws, name = _build_study(
        tmp_path, address="png:fig.png", fig_name="fig.png",
        fig_bytes_or_text=b"\x89PNG",
    )
    payload = build_study_charts_payload(ws, name)
    [rec] = [c for c in payload["charts"] if c.get("source") == "declared"]
    assert rec["media"] == "png"
    assert rec["img"].startswith("data:image/png;base64,")
    assert "iframe_url" not in rec

    status = viz_gate.study_visualization_status(ws, name)
    assert status["has_interactive"] is False


def test_declared_svg_figure_still_static_no_regression(tmp_path):
    ws, name = _build_study(
        tmp_path, address="svg:fig.svg", fig_name="fig.svg",
        fig_bytes_or_text="<svg><rect/></svg>",
    )
    payload = build_study_charts_payload(ws, name)
    [rec] = [c for c in payload["charts"] if c.get("source") == "declared"]
    assert rec["media"] == "svg"
    assert rec["svg"] == "<svg><rect/></svg>"

    status = viz_gate.study_visualization_status(ws, name)
    assert status["has_interactive"] is False


def test_declared_gif_figure_still_interactive_no_regression(tmp_path):
    ws, name = _build_study(
        tmp_path, address="gif:fig.gif", fig_name="fig.gif",
        fig_bytes_or_text=b"GIF89aFAKE",
    )
    payload = build_study_charts_payload(ws, name)
    [rec] = [c for c in payload["charts"] if c.get("source") == "declared"]
    assert rec["media"] == "gif"

    status = viz_gate.study_visualization_status(ws, name)
    assert status["has_interactive"] is True


# ---------------------------------------------------------------------------
# Real HTTP round-trip: GET /api/study-charts/<slug> must NOT strip
# `iframe_url` — ChartPayload is `extra="allow"` for exactly this kind of
# source-specific field, but that's worth pinning at the live-server seam
# (StudyChartsPayload is a real pydantic response_model, not a passthrough).
# ---------------------------------------------------------------------------

def test_study_charts_api_carries_iframe_url_and_media(tmp_path, dashboard_client):
    ws = tmp_path / "ws"
    study_dir = ws / "studies" / "demo3d"
    study_dir.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    (study_dir / "scene.html").write_text(
        "<html><body>3D scene</body></html>", encoding="utf-8")
    (study_dir / "study.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 3,
            "name": "demo3d",
            "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
            "variants": [],
            "visualizations": [
                {"name": "colony-3d", "address": "threejs:scene.html"},
            ],
        }),
        encoding="utf-8",
    )

    client = dashboard_client(ws)
    resp = client.get("/api/study-charts/demo3d")
    assert resp.status_code == 200
    body = resp.json()
    [rec] = [c for c in body["charts"] if c.get("source") == "declared"]
    assert rec["media"] == "threejs"
    assert rec["iframe_url"] == "/studies/demo3d/scene.html"

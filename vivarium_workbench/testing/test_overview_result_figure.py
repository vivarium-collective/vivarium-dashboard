"""Overview "Result" centerpiece must not overflow for loom figures.

Regression for the fig-01 overflow: when a study's primary `.svg` is a
bigraph-loom / react-flow diagram, its nodes are `<foreignObject>` HTML.
WebKit renders `<foreignObject>` at intrinsic size, ignoring the SVG's
viewBox->viewport scale — so an inlined `<svg>` with `max-width:100%` still
overflows its `.ctr-figure` container and bleeds over the Overview text.

The Visualizations tab already solved this (study-detail.js `_svgImg`) by
rasterizing such SVGs as an `<img data:image/svg+xml,...>` scaled with plain
`max-width` — correct in every engine. `render_study_detail_html` must do the
same for the Overview centerpiece.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from vivarium_workbench.lib.study_page import render_study_detail_html


_LOOM_SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="748" height="1311" '
    'viewBox="0 0 748 1311">'
    '<foreignObject x="0" y="0" width="748" height="1311">'
    '<div xmlns="http://www.w3.org/1999/xhtml" class="react-flow__viewport">'
    'gene_expression</div>'
    '</foreignObject></svg>'
)


def _render_with_primary_svg(svg_text: str) -> str:
    d = Path(tempfile.mkdtemp())
    sdir = d / "studies" / "figX"
    sdir.mkdir(parents=True)
    (sdir / "figX-loom.svg").write_text(svg_text, encoding="utf-8")
    spec = {
        "schema_version": 3,
        "name": "figX",
        "title": "Fig X",
        "status": "complete",
        "visualizations": [
            {"name": "figX-loom.svg", "address": "image:figX-loom.svg", "chart": "image"},
        ],
    }
    return render_study_detail_html(d, "figX", spec)


def test_loom_result_figure_is_rasterized_not_inline():
    """A foreignObject-bearing primary SVG renders as an <img> data-URI inside
    .ctr-figure, never as a raw inline <svg> (which overflows in WebKit)."""
    html = _render_with_primary_svg(_LOOM_SVG)
    # The centerpiece must be an <img> data-URI, not a raw inline <svg>.
    assert '<figure class="ctr-figure"><img' in html, (
        "Overview centerpiece should be an <img> data-URI, got:\n"
        + html[html.find("ctr-figure") - 10: html.find("ctr-figure") + 160]
    )
    assert "data:image/svg+xml," in html
    # No raw inline <svg> centerpiece (the overflowing path).
    assert '<figure class="ctr-figure"><svg' not in html

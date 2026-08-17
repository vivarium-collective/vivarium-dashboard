"""Post-run visualization of a ``tree[node]`` TOPOLOGY trajectory.

Composites whose place graph CHANGES as they run (cell division, biofilm
colonization, lineage evolution) emit a ``tree[node]`` store whose child nodes
appear/disappear over steps. The loom animates that live via the transport, but
a run should also leave a SAVED figure. This renders one: a self-contained HTML
with (1) a node-count-over-time chart per node type and (2) a filmstrip of the
place graph at each frame — so "the cells dividing and the biofilm forming" is
visible without re-running or scrubbing.

General: any run that captured a topology-changing ``tree[node]`` store gets it;
returns ``{}`` for runs that didn't (so it's a no-op for ordinary composites).
"""
from __future__ import annotations

import html as _html
from collections import Counter
from typing import Any

from vivarium_workbench.lib import composite_runs as cr

# _control → (fill, stroke). Extend freely; unknown controls fall back to grey.
_PALETTE: dict[str, tuple[str, str]] = {
    "cell": ("#d1fae5", "#059669"),
    "ecm": ("#fef3c7", "#d97706"),
    "organism": ("#dbeafe", "#2563eb"),
    "mutant": ("#fee2e2", "#dc2626"),
    "chromosome": ("#ede9fe", "#7c3aed"),
    "daughter": ("#cffafe", "#0891b2"),
}
_DEFAULT_COLOR = ("#e2e8f0", "#64748b")


def _tree_stores(state: dict) -> dict[str, dict]:
    if not isinstance(state, dict):
        return {}
    return {k: v for k, v in state.items()
            if isinstance(v, dict) and v.get("_type") == "tree[node]"}


def _nodes_by_control(tree: dict) -> list[tuple[str, str]]:
    """(key, _control) for each child node of a tree, in insertion order."""
    out: list[tuple[str, str]] = []
    for k, v in (tree or {}).items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and v.get("_control"):
            out.append((k, str(v["_control"])))
    return out


def _counts(tree: dict) -> Counter:
    c: Counter = Counter()
    for _k, ctrl in _nodes_by_control(tree):
        c[ctrl] += 1
    return c


def render_topology_viz(*, db_file: str, run_id: str) -> dict[str, str]:
    """Return ``{title: html}`` for a topology-changing run, else ``{}``."""
    conn = cr.connect(db_file)
    try:
        frames = cr.query_run(conn, run_id=run_id)
    finally:
        conn.close()
    if not frames or len(frames) < 2:
        return {}

    # Pick the tree[node] store whose total node count actually changes.
    first_state = frames[0].get("state", {}) or {}
    store_key = None
    for k in _tree_stores(first_state):
        totals = [sum(_counts(_tree_stores(f.get("state", {}) or {}).get(k, {})).values())
                  for f in frames]
        if len(set(totals)) > 1:
            store_key = k
            break
    if store_key is None:
        return {}

    per_frame: list[dict[str, Any]] = []
    controls: set[str] = set()
    for f in frames:
        tree = _tree_stores(f.get("state", {}) or {}).get(store_key, {})
        c = _counts(tree)
        controls |= set(c)
        per_frame.append({
            "step": f.get("step"), "time": f.get("time"),
            "counts": dict(c), "nodes": _nodes_by_control(tree),
        })
    controls_ordered = sorted(controls)
    return {f"Topology — {store_key}": _html_doc(store_key, per_frame, controls_ordered)}


def _color(ctrl: str) -> tuple[str, str]:
    return _PALETTE.get(ctrl, _DEFAULT_COLOR)


def _count_chart(per_frame: list[dict], controls: list[str]) -> str:
    """A small multi-series line chart (inline SVG) of counts over frames."""
    W, H, PAD = 520, 180, 28
    n = len(per_frame)
    ymax = max((sum(fr["counts"].values()) for fr in per_frame), default=1) or 1
    ymax = max(ymax, max((c for fr in per_frame for c in fr["counts"].values()), default=1))

    def x(i: int) -> float:
        return PAD + (W - 2 * PAD) * (i / max(1, n - 1))

    def y(v: float) -> float:
        return H - PAD - (H - 2 * PAD) * (v / ymax)

    parts = [f'<svg viewBox="0 0 {W} {H}" class="tv-chart" role="img">']
    # axes
    parts.append(f'<line x1="{PAD}" y1="{H-PAD}" x2="{W-PAD}" y2="{H-PAD}" stroke="#cbd5e1"/>')
    parts.append(f'<line x1="{PAD}" y1="{PAD}" x2="{PAD}" y2="{H-PAD}" stroke="#cbd5e1"/>')
    for gy in (0, ymax):
        parts.append(f'<text x="{PAD-6}" y="{y(gy)+4}" text-anchor="end" class="tv-ax">{int(gy)}</text>')
    parts.append(f'<text x="{W/2}" y="{H-4}" text-anchor="middle" class="tv-ax">frame →</text>')
    for ctrl in controls:
        fill, stroke = _color(ctrl)
        pts = " ".join(f"{x(i):.1f},{y(fr['counts'].get(ctrl,0)):.1f}" for i, fr in enumerate(per_frame))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="2.5" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
        # endpoint dot + label
        lx, ly = x(n - 1), y(per_frame[-1]["counts"].get(ctrl, 0))
        parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{stroke}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _frame_svg(nodes: list[tuple[str, str]]) -> str:
    """A tiny place-graph glyph for one frame: the root with its child nodes."""
    cols = 4
    cw, ch, r = 34, 30, 60
    rows = (len(nodes) + cols - 1) // cols or 1
    W = cols * cw + 12
    H = r + rows * ch + 10
    parts = [f'<svg viewBox="0 0 {W} {H}" class="tv-frame">']
    # root store
    parts.append(f'<rect x="6" y="6" width="{W-12}" height="{H-12}" rx="7" '
                 f'fill="#f8fafc" stroke="#cbd5e1" stroke-dasharray="3,3"/>')
    for i, (_k, ctrl) in enumerate(nodes):
        fill, stroke = _color(ctrl)
        cx = 6 + (i % cols) * cw + cw / 2
        cy = r - 18 + (i // cols) * ch + ch / 2
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="9" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    parts.append("</svg>")
    return "".join(parts)


def _html_doc(store_key: str, per_frame: list[dict], controls: list[str]) -> str:
    legend = "".join(
        f'<span class="tv-leg"><span class="tv-swatch" style="background:{_color(c)[0]};'
        f'border-color:{_color(c)[1]}"></span>{_html.escape(c)}</span>'
        for c in controls)
    # Filmstrip: cap at ~24 frames so a long run stays legible; sample evenly.
    fr = per_frame
    if len(fr) > 24:
        idx = [round(i * (len(fr) - 1) / 23) for i in range(24)]
        fr = [per_frame[i] for i in sorted(set(idx))]
    strip = "".join(
        f'<figure class="tv-cell">{_frame_svg(f["nodes"])}'
        f'<figcaption>{("t=%g" % f["time"]) if f.get("time") is not None else ("#%s" % f.get("step"))}'
        f' · {sum(f["counts"].values())}</figcaption></figure>'
        for f in fr)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      body {{ font: 13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:#1e293b; margin:0; padding:14px; background:#fff; }}
      h3 {{ margin:0 0 2px; font-size:15px; }}
      .tv-sub {{ color:#64748b; margin:0 0 12px; }}
      .tv-legendbar {{ display:flex; gap:14px; flex-wrap:wrap; margin:8px 0 14px; }}
      .tv-leg {{ display:inline-flex; align-items:center; gap:6px; font-size:12px; color:#475569; }}
      .tv-swatch {{ width:12px; height:12px; border-radius:3px; border:1.5px solid; display:inline-block; }}
      .tv-chart {{ width:100%; max-width:540px; height:auto; }}
      .tv-ax {{ font-size:10px; fill:#94a3b8; }}
      .tv-strip {{ display:flex; gap:8px; overflow-x:auto; padding:6px 2px 10px; }}
      .tv-cell {{ margin:0; flex:none; text-align:center; }}
      .tv-frame {{ width:78px; height:auto; display:block; }}
      .tv-cell figcaption {{ font-size:10px; color:#64748b; margin-top:2px; font-variant-numeric:tabular-nums; }}
      .tv-h {{ font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; color:#94a3b8; margin:14px 0 4px; }}
    </style></head><body>
      <h3>Place-graph topology forming — {_html.escape(store_key)}</h3>
      <p class="tv-sub">How the composite's place graph grows as it runs — node count over time, then the graph at each captured frame.</p>
      <div class="tv-legendbar">{legend}</div>
      <div class="tv-h">Node count over time</div>
      {_count_chart(per_frame, controls)}
      <div class="tv-h">Place graph, frame by frame</div>
      <div class="tv-strip">{strip}</div>
    </body></html>"""

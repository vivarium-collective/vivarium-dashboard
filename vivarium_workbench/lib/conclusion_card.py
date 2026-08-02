"""The study "Decide" tab's three-track verdict as a DEFAULT report card.

Mirrors the ``study_verdict.write_gate_evaluator`` precedent (a viva_superpowers
spine helper): compute a derived verdict from the study's canonical fields, then
persist it as a workflow artifact so a render can prefer the persisted copy over
a live recompute. Here the artifact is a report card
(``viz/report_card/conclusion.{html,verdict.json}``) rather than a study.yaml
field, so it plugs into the SAME report-card + findings machinery every other
report card uses (``report_card_urls``, ``derive_findings_from_report_cards``)
instead of inventing a parallel concept.

The verdict computation itself is NOT duplicated here — ``build_conclusion_verdict``
calls the single canonical rule, ``study_derivations.conclusion_verdicts``, so the
persisted card and the study-detail render's fallback recompute can never diverge
in WHAT they compute, only in WHEN.
"""
from __future__ import annotations

import html as _html
import json
import sys
from pathlib import Path

import yaml

from vivarium_workbench.lib import study_derivations
from vivarium_workbench.lib.atomic_io import atomic_write_text

SCHEMA = "conclusion_card/v1"

# (track key, display label, "from <basis_hint>" caption) — order matches the
# Decide tab's own render (static/walkthrough.js `_conclusionVerdictsHtml`).
_TRACKS = (
    ("biological_validation", "Empirical validation", "gate evaluator"),
    ("regression_compatibility", "Regression compatibility", "run status"),
    ("explanatory_gain", "Explanatory gain", "interpretation-tier findings"),
)

# Maps a track's PASS/PARTIAL/FAIL/PENDING/GAP token onto the canonical
# report-card vocabulary (`_REPORT_CARD_VERDICTS` in study_spec.py: within_tol /
# drift / mismatch / ungraded) so this card's `overall` reads like any other
# report card's verdict pill in report_card_urls / the Report Cards tab.
_RESULT_TO_CANON = {
    "PASS": "within_tol", "PARTIAL": "drift", "FAIL": "mismatch",
    "PENDING": "ungraded", "GAP": "ungraded",
}
# Higher = worse (mirrors study_spec._VERDICT_SEVERITY). `overall` is the worst
# of the three tracks.
_CANON_SEVERITY = {"mismatch": 3, "drift": 2, "within_tol": 1, "ungraded": 0}

# Same badge palette as the Decide tab's live render (walkthrough.js `_TRACK_COLORS`).
_TRACK_COLORS = {
    "PASS": ("#dcfce7", "#166534"),
    "PARTIAL": ("#fef3c7", "#92400e"),
    "FAIL": ("#fee2e2", "#991b1b"),
    "GAP": ("#f1f5f9", "#475569"),
    "PENDING": ("#f1f5f9", "#475569"),
}


def build_conclusion_verdict(spec: dict) -> dict:
    """Compute the conclusion card's verdict.json payload from a study spec.

    ``spec`` should already carry the evidence chain the Decide tab renders
    from (authored or report-card-derived ``findings``, ``runs``,
    ``pipeline_gate``/``gate_status``) — this function is pure and does no I/O.
    """
    tracks = study_derivations.conclusion_verdicts(spec if isinstance(spec, dict) else {})
    canon = {
        name: _RESULT_TO_CANON.get((t or {}).get("result"), "ungraded")
        for name, t in tracks.items()
    }
    overall = (
        max(canon.values(), key=lambda c: _CANON_SEVERITY.get(c, 0))
        if canon else "ungraded"
    )
    return {
        "schema": SCHEMA,
        "overall": overall,
        "tracks": tracks,
        "insight": study_derivations.insight(spec if isinstance(spec, dict) else {}),
    }


def render_conclusion_html(verdict: dict, spec: dict) -> str:
    """Compact self-contained HTML render of the three-track verdict.

    Carries the ``viv-artifact: report-card`` marker (``REPORT_CARD_MARKER`` in
    study_spec.py) so the study-detail loader's content-sniff classifies this as
    a report card regardless of where it's embedded.
    """
    verdict = verdict if isinstance(verdict, dict) else {}
    spec = spec if isinstance(spec, dict) else {}
    name = spec.get("name") or spec.get("title") or "study"
    tracks = verdict.get("tracks") or {}
    insight = verdict.get("insight") or ""

    rows = []
    for key, label, basis_hint in _TRACKS:
        t = tracks.get(key) or {}
        res = str(t.get("result") or "PENDING")
        bg, fg = _TRACK_COLORS.get(res, _TRACK_COLORS["PENDING"])
        basis = (t.get("basis") or "").strip()
        basis_html = (
            '<div style="color:#475569;font-size:0.9em;margin-top:2px">'
            f'{_html.escape(basis)}</div>'
            if basis else ""
        )
        rows.append(
            '<div style="padding:8px 0;border-top:1px solid #f1f5f9">'
            '<div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">'
            '<span style="display:inline-block;min-width:11em;font-weight:600;'
            f'color:#1e293b">{_html.escape(label)}</span>'
            '<span style="display:inline-block;padding:2px 10px;border-radius:9999px;'
            f'background:{bg};color:{fg};font-weight:700;font-size:0.85em">'
            f'{_html.escape(res)}</span>'
            '<span style="color:#94a3b8;font-size:0.82em">'
            f'from {_html.escape(basis_hint)} · computed</span>'
            "</div>" + basis_html + "</div>"
        )

    insight_html = (
        '<p style="color:#334155;font-style:italic;margin:14px 0 0 0">'
        f"{_html.escape(insight)}</p>"
        if insight else ""
    )

    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        '<meta name="viv-artifact" content="report-card">'
        f"<title>{_html.escape(str(name))} — conclusion report card</title>"
        "</head><body style=\"font-family:system-ui,sans-serif;max-width:720px;"
        'margin:24px auto;padding:0 16px;color:#0f172a">'
        '<h3 style="margin:0 0 4px 0">Conclusion</h3>'
        '<p style="color:#64748b;font-size:0.9em;margin:0 0 8px 0">'
        "Three-track verdict, computed from canonical fields (gate evaluator, "
        "run status, finding tiers) and persisted at the end of each run."
        "</p>" + "".join(rows) + insight_html + "</body></html>"
    )


def _infer_ws_root(study_dir: Path) -> Path:
    """Best-effort workspace root from a study directory alone.

    Walks up looking for ``workspace.yaml`` (the canonical marker); falls back
    to the classic two-levels-up ``studies/<slug>`` / ``investigations/<slug>``
    layout when no ``workspace.yaml`` is found (e.g. a hermetic test fixture).
    """
    study_dir = Path(study_dir)
    for p in (study_dir, *study_dir.parents):
        if (p / "workspace.yaml").is_file():
            return p
    parent = study_dir.parent
    if parent.name in ("studies", "investigations"):
        return parent.parent
    return parent


def write_conclusion_card(study_dir) -> bool:
    """Compute + atomically persist a study's conclusion report card.

    Writes ``<study_dir>/viz/report_card/conclusion.html`` and
    ``conclusion.verdict.json``. Idempotent: a second call whose inputs haven't
    changed writes nothing and returns ``False``. NEVER raises — any failure
    (missing study.yaml, malformed YAML, unexpected shape) degrades to a no-op
    ``False`` so a post-run flush stage can call this unconditionally.
    """
    try:
        study_dir = Path(study_dir)
        from vivarium_workbench.lib import study_spec

        sf = study_spec.study_spec_file(study_dir)
        if not sf.is_file():
            return False
        spec = yaml.safe_load(sf.read_text(encoding="utf-8")) or {}
        if not isinstance(spec, dict):
            return False

        from vivarium_workbench.lib.spec_migration import migrate_v2_to_v3
        spec = migrate_v2_to_v3(spec)
        if spec.get("schema_version") == 4 and isinstance(spec.get("conditions"), dict):
            from vivarium_workbench.lib.investigations import (
                _project_v4_redesign_to_legacy_view,
            )
            spec = _project_v4_redesign_to_legacy_view(spec)

        ws_root = _infer_ws_root(study_dir)
        name = spec.get("name") or study_dir.name

        # Same evidence chain the Decide-tab render uses: authored findings win
        # unchanged; otherwise derive one finding per OTHER report card. This
        # NEVER includes this card itself — derive_findings_from_report_cards
        # excludes the `conclusion` card by construction (the feedback-loop
        # guard: this card is the verdict, not evidence for itself) — so
        # explanatory_gain here can't be fed by its own prior output.
        try:
            findings, _rc_urls = study_spec.report_card_findings_for_study(
                ws_root, name, spec.get("findings"))
            if findings:
                spec = dict(spec)
                spec["findings"] = findings
        except Exception:  # noqa: BLE001 — best-effort enrichment only
            pass

        verdict = build_conclusion_verdict(spec)
        html_text = render_conclusion_html(verdict, spec)
        verdict_text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"

        rc_dir = study_dir / "viz" / "report_card"
        verdict_path = rc_dir / "conclusion.verdict.json"
        html_path = rc_dir / "conclusion.html"

        old_verdict = (
            verdict_path.read_text(encoding="utf-8") if verdict_path.is_file() else None
        )
        old_html = html_path.read_text(encoding="utf-8") if html_path.is_file() else None
        if old_verdict == verdict_text and old_html == html_text:
            return False

        rc_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(verdict_path, verdict_text)
        atomic_write_text(html_path, html_text)
        return True
    except Exception as exc:  # noqa: BLE001 — never fail a run over a report card
        print(f"[conclusion_card] write failed: {exc}", file=sys.stderr)
        return False

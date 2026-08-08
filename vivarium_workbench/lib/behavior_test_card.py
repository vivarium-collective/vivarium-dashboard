"""behavior_test_card.py — the DEFAULT report card every study gets.

A study's behavior tests ARE a report card: this module synthesizes
``viz/report_card/behavior-tests.{html,verdict.json}`` from the study's
``behavior_tests`` and the per-run ``runs[].outcomes`` that ``auto_evaluate``
fills. It renders under Report Cards like any other card (discovered by
``saved_visualizations``, carrying the ``report-card`` marker + a ``verdict.json``
``overall``), and it is the one card that also grades the study.

Mirrors ``conclusion_card`` (same synthesized-card pattern, atomic + idempotent
write, never-raise); the two are parallel default cards written in the post-run
flush. The behavior-test evaluation itself is NOT duplicated here — the results
come from ``runs[].outcomes`` (written by ``auto_evaluate`` /
``study_evaluator``).

``verdict.json`` shape: ``{schema, overall, tests: [...], n_pass, n_fail, n_total}``
where ``overall`` is the canonical report-card vocabulary
(``within_tol``/``drift``/``mismatch``/``ungraded``) so it reads like any other
card's pill. Rollup: any FAIL → ``mismatch``; else all PASS → ``within_tol``;
else (any SKIP / pending / partial) → ``drift``; no tests → ``ungraded``.
"""
from __future__ import annotations

import html as _html
import json
import sys
from pathlib import Path

import yaml

from vivarium_workbench.lib.atomic_io import atomic_write_text
from vivarium_workbench.lib.conclusion_card import _TRACK_COLORS

SCHEMA = "behavior_test_card/v1"


def _outcomes_by_test(spec: dict) -> dict:
    """Merge per-run ``outcomes`` keyed by test name; a ``canonical`` run wins."""
    merged: dict = {}
    for run in spec.get("runs") or []:
        if not isinstance(run, dict):
            continue
        oc = run.get("outcomes")
        if not isinstance(oc, dict):
            continue
        canonical = bool(run.get("canonical"))
        for tname, o in oc.items():
            if canonical or tname not in merged:
                merged[tname] = o if isinstance(o, dict) else {}
    return merged


def build_behavior_tests_verdict(spec: dict) -> dict:
    """Compute the behavior-tests card verdict.json payload. Pure; no I/O."""
    spec = spec if isinstance(spec, dict) else {}
    tests = [t for t in (spec.get("behavior_tests") or spec.get("expected_behavior") or [])
             if isinstance(t, dict)]
    outcomes = _outcomes_by_test(spec)

    rows: list[dict] = []
    for t in tests:
        name = str(t.get("name") or "")
        o = outcomes.get(name) or {}
        result = str(o.get("result") or "PENDING").upper()
        rows.append({
            "name": name,
            "en": str(t.get("en") or t.get("description") or "").strip(),
            "result": result,
            "detail": str(o.get("detail") or o.get("note") or "").strip(),
            "measured_value": o.get("measured_value"),
        })

    results = [r["result"] for r in rows]
    if not results:
        overall = "ungraded"
    elif any(r == "FAIL" for r in results):
        overall = "mismatch"
    elif all(r == "PASS" for r in results):
        overall = "within_tol"
    else:
        overall = "drift"  # any SKIP / pending / partial

    return {
        "schema": SCHEMA,
        "overall": overall,
        "tests": rows,
        "n_pass": sum(1 for r in results if r == "PASS"),
        "n_fail": sum(1 for r in results if r == "FAIL"),
        "n_total": len(rows),
    }


def render_behavior_tests_html(verdict: dict, spec: dict) -> str:
    """Compact self-contained HTML for the behavior-tests report card.

    Carries the ``viv-artifact: report-card`` marker so the study-detail loader
    classifies it as a report card wherever embedded.
    """
    from vivarium_workbench.lib.study_spec import REPORT_CARD_MARKER

    verdict = verdict if isinstance(verdict, dict) else {}
    spec = spec if isinstance(spec, dict) else {}
    name = spec.get("name") or spec.get("title") or "study"
    rows = verdict.get("tests") or []
    n_pass, n_fail = verdict.get("n_pass", 0), verdict.get("n_fail", 0)
    n_total = verdict.get("n_total", 0)

    body_rows = []
    for r in rows:
        res = str(r.get("result") or "PENDING")
        bg, fg = _TRACK_COLORS.get(res, _TRACK_COLORS["PENDING"])
        detail = r.get("detail") or ""
        mv = r.get("measured_value")
        meta = detail or (f"measured: {mv}" if mv is not None else "")
        meta_html = (
            '<div style="color:#475569;font-size:0.88em;margin-top:2px">'
            f'{_html.escape(str(meta))}</div>' if meta else ""
        )
        en_html = (
            '<div style="color:#334155;font-size:0.9em">'
            f'{_html.escape(str(r.get("en") or ""))}</div>' if r.get("en") else ""
        )
        body_rows.append(
            '<div style="padding:8px 0;border-top:1px solid #f1f5f9">'
            '<div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">'
            '<span style="display:inline-block;padding:2px 10px;border-radius:9999px;'
            f'background:{bg};color:{fg};font-weight:700;font-size:0.82em">{_html.escape(res)}</span>'
            '<span style="font-weight:600;color:#1e293b">'
            f'{_html.escape(str(r.get("name") or ""))}</span>'
            "</div>" + en_html + meta_html + "</div>"
        )

    if not rows:
        body_rows.append(
            '<p style="color:#64748b;font-style:italic;margin:8px 0">'
            'No behavior_tests declared yet — add acceptance criteria to grade this study.</p>'
        )

    summary = (
        f'<span style="color:#166534;font-weight:600">{n_pass} pass</span>'
        + (f' · <span style="color:#991b1b;font-weight:600">{n_fail} fail</span>' if n_fail else "")
        + f' · {n_total} total'
    ) if n_total else "no tests"

    return (
        REPORT_CARD_MARKER + "\n"
        '<div style="font-family:system-ui,-apple-system,sans-serif;max-width:52rem">'
        f'<h3 style="margin:0 0 2px 0;color:#0f172a">Behavior tests — {_html.escape(str(name))}</h3>'
        f'<div style="color:#64748b;font-size:0.9em;margin-bottom:6px">{summary}</div>'
        + "".join(body_rows)
        + "</div>"
    )


def render_behavior_card_response(ws_root, slug) -> tuple[str, int]:
    """Render a study's behavior-tests card on demand (read-only; no file write).

    Backs ``GET /api/study-behavior-card/<slug>`` so a study that has not yet
    produced the on-disk ``behavior-tests.html`` artifact (e.g. still in Design,
    never run) can still surface the default card. Returns ``(html, status)``:
    404 when the study has no spec, 200 otherwise, 500 on an unexpected error.
    """
    try:
        from vivarium_workbench.lib import study_spec
        sf = study_spec.study_spec_path(Path(ws_root), str(slug))
        if not sf.is_file():
            return "<h1>Study not found</h1>", 404
        spec = yaml.safe_load(sf.read_text(encoding="utf-8")) or {}
        if not isinstance(spec, dict):
            return "<h1>Study spec invalid</h1>", 404
        from vivarium_workbench.lib.spec_migration import migrate_v2_to_v3
        spec = migrate_v2_to_v3(spec)
        verdict = build_behavior_tests_verdict(spec)
        return render_behavior_tests_html(verdict, spec), 200
    except Exception as exc:  # noqa: BLE001
        return (
            "<h1>Behavior-tests card error</h1>"
            f"<pre>{_html.escape(str(exc))}</pre>", 500
        )


def write_behavior_test_card(study_dir) -> bool:
    """Compute + atomically persist a study's behavior-tests report card.

    Writes ``<study_dir>/viz/report_card/behavior-tests.{html,verdict.json}``.
    Idempotent (no write when unchanged → returns False). NEVER raises — any
    failure degrades to a no-op ``False`` so a post-run flush stage can call it
    unconditionally.
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

        verdict = build_behavior_tests_verdict(spec)
        html_text = render_behavior_tests_html(verdict, spec)
        verdict_text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"

        rc_dir = study_dir / "viz" / "report_card"
        verdict_path = rc_dir / "behavior-tests.verdict.json"
        html_path = rc_dir / "behavior-tests.html"

        old_verdict = verdict_path.read_text(encoding="utf-8") if verdict_path.is_file() else None
        old_html = html_path.read_text(encoding="utf-8") if html_path.is_file() else None
        if old_verdict == verdict_text and old_html == html_text:
            return False

        rc_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(verdict_path, verdict_text)
        atomic_write_text(html_path, html_text)
        return True
    except Exception as exc:  # noqa: BLE001 — never fail a run over a report card
        print(f"[behavior_test_card] write failed: {exc}", file=sys.stderr)
        return False

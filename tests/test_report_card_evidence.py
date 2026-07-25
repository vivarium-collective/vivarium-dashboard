"""Deterministic derivation of study findings from report cards.

When a study carries report cards but no authored ``findings``, its evidence
chain would render blank. These helpers derive one finding per report card from
the card's own verdict badge + title, so the investigation graph shows "Finds:…"
and the study pillar reflects the evidence — without clobbering authored findings.
"""
from __future__ import annotations

import json
from pathlib import Path

from vivarium_workbench.lib.study_spec import (
    _report_card_verdict_and_subject,
    _normalize_verdict,
    derive_findings_from_report_cards,
)


# --- fixtures ---------------------------------------------------------------

def _write(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _card_html(title: str, badge_token: str, tallies: str) -> str:
    """A minimal report-card HTML: a <title> and an overall badge span.

    The CSS block deliberately names every verdict class (as real cards do) so
    the test proves the extractor reads ONLY the badge, not the stylesheet.
    """
    return (
        "<html><head><title>" + title + "</title>"
        "<style>.verdict-within_tol{} .verdict-drift{} .verdict-mismatch{} "
        ".verdict-ungraded{}</style></head><body>"
        '<span class="obadge">' + badge_token
        + " &nbsp;·&nbsp; " + tallies + "</span>"
        "</body></html>"
    )


# --- (a) verdict + subject + counts extraction ------------------------------

def test_extracts_verdict_subject_counts_from_badge(tmp_path):
    p = _write(
        tmp_path / "1-fba-bridge.html",
        _card_html(
            "v2ecoli baseline vs Millard FBA-bridge — central-carbon exchange — report card",
            "MISMATCH", "1 ✓ &nbsp; 0 ≈ &nbsp; 3 ✗ &nbsp; 0 –"),
    )
    verdict, subject, counts = _report_card_verdict_and_subject(p)
    assert verdict == "mismatch"
    assert subject == "v2ecoli baseline vs Millard FBA-bridge — central-carbon exchange"
    assert counts == {"within_tol": 1, "drift": 0, "mismatch": 3, "ungraded": 0}


def test_pass_badge_normalizes_to_within_tol(tmp_path):
    p = _write(tmp_path / "4-ode.html",
               _card_html("A vs B — report card", "PASS", "1 ✓ 0 ≈ 0 ✗ 0 –"))
    verdict, _subject, counts = _report_card_verdict_and_subject(p)
    assert verdict == "within_tol"
    assert counts["within_tol"] == 1


def test_normalize_verdict_aliases():
    assert _normalize_verdict("MISMATCH") == "mismatch"
    assert _normalize_verdict("PASS") == "within_tol"
    assert _normalize_verdict("within tol") == "within_tol"
    assert _normalize_verdict("Drift") == "drift"
    assert _normalize_verdict("") is None
    assert _normalize_verdict("banana") is None


# --- (b) verdict.json sibling preferred over HTML ---------------------------

def test_verdict_json_sibling_preferred_over_html(tmp_path):
    _write(tmp_path / "c.html",
           _card_html("X vs Y — report card", "MISMATCH", "0 ✓ 0 ≈ 4 ✗ 0 –"))
    # Sibling says within_tol — that must win over the HTML badge's MISMATCH.
    (tmp_path / "c.verdict.json").write_text(json.dumps({"overall": "within_tol"}))
    verdict, _subject, _counts = _report_card_verdict_and_subject(tmp_path / "c.html")
    assert verdict == "within_tol"


# --- (c) derivation: one finding per card, sorted, right keys ---------------

def test_derivation_one_finding_per_card_sorted(tmp_path):
    ws = tmp_path
    _write(ws / "reports/figures/s/1-fba.html",
           _card_html("Baseline vs FBA — exchange — report card", "MISMATCH", "1 ✓ 0 ≈ 3 ✗ 0 –"))
    _write(ws / "reports/figures/s/2-ode.html",
           _card_html("Baseline vs ODE — exchange — report card", "PASS", "1 ✓ 0 ≈ 0 ✗ 0 –"))
    # report_card_urls as the promotion path would produce them (keyed by stem).
    rc_urls = {
        "2-ode": {"url": "/reports/figures/s/2-ode.html", "verdict": None},
        "1-fba": {"url": "/reports/figures/s/1-fba.html", "verdict": None},
    }
    findings = derive_findings_from_report_cards(ws, "s", rc_urls, None)

    assert len(findings) == 2
    # Deterministic order: sorted by card key.
    assert [f["id"] for f in findings] == ["report-card-1-fba", "report-card-2-ode"]
    f0 = findings[0]
    # Exact key shape the SPA finding readers consume.
    assert set(f0) >= {"id", "summary", "statement", "status", "kind",
                       "verdict", "source", "url", "evidence"}
    assert f0["source"] == "report_card"
    assert f0["verdict"] == "mismatch"
    assert f0["status"] == "contradicts"          # mismatch → ✗
    assert f0["url"] == "/reports/figures/s/1-fba.html"
    assert findings[1]["status"] == "confirms"    # within_tol → ✓
    # Verdicts were backfilled onto the report_card_urls entries.
    assert rc_urls["1-fba"]["verdict"] == "mismatch"
    assert rc_urls["2-ode"]["verdict"] == "within_tol"


# --- (d) authored findings are NOT clobbered --------------------------------

def test_authored_findings_not_clobbered(tmp_path):
    authored = [{"id": "hand-written", "statement": "the author's own claim"}]
    rc_urls = {"1-fba": {"url": "/x.html", "verdict": None}}
    out = derive_findings_from_report_cards(tmp_path, "s", rc_urls, authored)
    assert out is authored
    # No derivation ran, so no backfill either.
    assert rc_urls["1-fba"]["verdict"] is None


# --- (e) a real figure yields NO verdict/finding ----------------------------

def test_real_figure_has_no_verdict(tmp_path):
    # A plot: title without "report card", no badge span.
    p = _write(tmp_path / "5-nadh.html",
               "<html><head><title>KETCHUP FDH dynamic fit — NADH(t)</title>"
               "</head><body>plot</body></html>")
    verdict, subject, counts = _report_card_verdict_and_subject(p)
    assert verdict is None
    assert counts is None
    # Its title is NOT stripped of a "report card" suffix (there is none).
    assert subject == "KETCHUP FDH dynamic fit — NADH(t)"


def test_empty_report_cards_yields_no_findings(tmp_path):
    assert derive_findings_from_report_cards(tmp_path, "s", {}, None) == []
    assert derive_findings_from_report_cards(tmp_path, "s", None, None) == []

"""Regression cover for: per-run artifact links (Viz/Report/Analyses/Results,
study export/analysis-zip, the audit report) are plain markup (href/window.open/
window.location), not fetch/XHR/EventSource — so report.py's base-path shim never
sees them. Under the co-tenant ALB (serve --base-path /workbench), an unprefixed
"/api/…" href/open/location routes to sms-api instead of the workbench (404),
exactly like the "Composites tab → Run → 404" bug test_composite_explore_base_path
guards against, but for the run-download surface instead of composite-explore.
"""
from __future__ import annotations

import re
from pathlib import Path

import vivarium_workbench

_STATIC = Path(vivarium_workbench.__file__).parent / "static"


def _txt(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def test_no_bare_api_hrefs_or_navigations():
    # A bare literal immediately after href=/window.open(/window.location = is
    # exactly the pattern that escapes the shim. window.__BASE_PATH__ (or a `BP`
    # alias of it) must appear on the same line as every such construction.
    bare_re = re.compile(
        r"""(?:href=["']/api|window\.open\(\s*["']/api|window\.location\s*=\s*["']/api)"""
    )
    # composite-card.js (study-spine-reorg Task 6): shared composite-card
    # renderer extracted out of walkthrough.js — same guard applies.
    for fname in ("sim-table.js", "study-detail.js", "walkthrough.js", "composite-card.js"):
        js = _txt(fname)
        for lineno, line in enumerate(js.splitlines(), start=1):
            assert not bare_re.search(line), (
                f"{fname}:{lineno}: bare (un-base-path'd) /api href/open/location: "
                f"{line.strip()[:100]}"
            )


def test_run_artifact_links_are_base_path_prefixed():
    # Spot-check the specific call sites this bug was found on: each constructs
    # its href/open/location target with a __BASE_PATH__ (or BP) prefix.
    checks = [
        ("sim-table.js", "/api/composite-run/"),
        ("sim-table.js", "/api/simulation-run-download"),
        ("study-detail.js", "/api/simulation-run-download"),
        ("study-detail.js", "/api/study-analysis-zip"),
        ("study-detail.js", "/api/study-export"),
        ("walkthrough.js", "/api/audit-report"),
    ]
    for fname, endpoint in checks:
        js = _txt(fname)
        assert endpoint in js, f"{fname}: expected endpoint {endpoint!r} not found"
        # The endpoint string itself must be preceded by a BASE_PATH/BP reference
        # within the same statement (i.e. string concatenation), not a lone literal.
        idx = js.index(endpoint)
        window = js[max(0, idx - 80):idx]
        assert "__BASE_PATH__" in window or "BP" in window, (
            f"{fname}: {endpoint!r} is not base-path prefixed (no __BASE_PATH__/BP "
            f"reference in the preceding 80 chars: {window!r})"
        )

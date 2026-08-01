"""The Visualizations empty-state message must be format-agnostic.

``runs.db`` is run *metadata*, created for every run regardless of emitter;
the framework default emitter is xarray/zarr, so a zarr-backed study with
real trajectory data has no ``runs.db`` history at all. The old hardcoded
"No runs.db and no static charts..." string named the wrong store and gave
the reader nothing to act on. It must say something format-agnostic instead
— and must NOT substitute in ``runs.jsonl`` either, since that log holds no
plottable data (see ``lib/run_log.py``); naming it would just move the same
false claim to a different file.

No JS execution harness exists in this suite (see
``test_derivations_js_dedup.py`` for the established pattern) — these are
source-text assertions on the shipped bundle.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SD = ROOT / "vivarium_workbench/static/study-detail.js"


def test_empty_state_is_format_agnostic():
    js = SD.read_text(encoding="utf-8")
    assert "No run data or figures yet for this study." in js


def test_empty_state_does_not_name_runs_db():
    js = SD.read_text(encoding="utf-8")
    assert "No <code>runs.db</code>" not in js
    assert "no static charts under <code>studies/" not in js


def test_empty_state_does_not_substitute_runs_jsonl():
    """Confirm the fix didn't just rename the misleading string to jsonl —
    runs.jsonl is a pure event log with no plottable data."""
    js = SD.read_text(encoding="utf-8")
    assert "No <code>runs.jsonl</code>" not in js
    assert "runs.jsonl" not in js

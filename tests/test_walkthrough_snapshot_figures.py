"""Regression: the investigation ↓ figures button must appear in read-only snapshots.

The button is injected async into #ws-actions-figures after fetching
/api/investigation-summaries and checking n_figures > 0. That fetch was a RAW
`fetch('/api/investigation-summaries')` with no snapshot adaptation, so in a static
bundle it 404s (the baked file is /api/investigation-summaries.json), the `.then`
never runs, and the ↓ figures button never appears — even though the figures.zip is
baked. The fetch must go through the `_api()` snapshot-URL adapter (or a
window.DataSource loader), same as every other data fetch.
"""
from pathlib import Path

import vivarium_workbench


def _js() -> str:
    return (Path(vivarium_workbench.__file__).parent / "static" / "walkthrough.js").read_text(
        encoding="utf-8"
    )


def test_investigation_actions_summaries_fetch_is_snapshot_adapted():
    js = _js()
    # the button-gating fetch goes through the _api() adapter
    assert "fetch(_api('/api/investigation-summaries'), {headers: {Accept: 'application/json'}})" in js


def test_no_unguarded_raw_summaries_fetch_remains():
    """A bare fetch('/api/investigation-summaries') is only allowed as the else-branch
    of a `window.DataSource ? DataSource.loadIsetList() : ...` guard (DataSource is
    always present in a published bundle, so that fallback never runs). Any raw fetch
    NOT preceded by such a guard is the snapshot bug."""
    js = _js()
    for idx, line in enumerate(js.splitlines()):
        if "fetch('/api/investigation-summaries'" in line:
            # the two lines above must show the DataSource ternary fallback form
            context = "\n".join(js.splitlines()[max(0, idx - 2):idx + 1])
            assert "DataSource" in context and ":" in line, (
                f"unguarded raw summaries fetch at line {idx + 1}: {line.strip()}"
            )

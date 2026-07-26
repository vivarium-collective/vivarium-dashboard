"""UI: compatible-analysis-tools launch chips on the Simulations DB rows.

Cheap "the wiring exists" checks against the live FastAPI app (via
``dashboard_client``) and the served static JS/HTML, mirroring
tests/test_rerun_ui.py's style — not exhaustive JS behavior tests (this repo
has no JS execution harness for sim-table.js), just confirmation that the
frontend piece is actually wired up alongside the backend `matched_tools`
data (tests/test_simulations_matched_tools.py).
"""
from __future__ import annotations

import shutil
from pathlib import Path

_FIXTURE = Path(__file__).parent / "_fixtures" / "ws_increase_demo"


def _ws_copy(tmp_path):
    ws = tmp_path / "ws"
    shutil.copytree(_FIXTURE, ws)
    return ws


def test_sim_table_js_renders_matched_tools_chips(dashboard_client, tmp_path):
    client = dashboard_client(workspace=_ws_copy(tmp_path))
    r = client.get("/sim-table.js")
    assert r.status_code == 200
    assert "matched_tools" in r.text
    assert "tool-launch-btn" in r.text
    assert "toolsCell" in r.text


def test_index_html_has_tools_column(dashboard_client, tmp_path):
    client = dashboard_client(workspace=_ws_copy(tmp_path))
    r = client.get("/")
    assert r.status_code == 200
    assert ">Tools</th>" in r.text

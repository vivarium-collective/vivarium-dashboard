"""Live endpoint: GET /api/analysis-tools.

Exercises the tools-first Analysis Tools tab endpoint against a throwaway
copy of the ws_increase_demo fixture. The fixture has no runs/packs, so
built-in tools appear with an empty `matched` list.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent / "_fixtures" / "ws_increase_demo"


@pytest.fixture
def ws_copy(tmp_path):
    ws = tmp_path / "ws"
    shutil.copytree(_FIXTURE, ws)
    return ws


def test_analysis_tools_endpoint(dashboard_client, ws_copy):
    client = dashboard_client(workspace=ws_copy)
    r = client.get("/api/analysis-tools")
    assert r.status_code == 200
    body = r.json()
    assert "tools" in body
    ids = {t["id"] for t in body["tools"]}
    assert {"data-explorer", "parsimony-viewer"} <= ids
    for t in body["tools"]:
        assert "requires" in t and "matched" in t

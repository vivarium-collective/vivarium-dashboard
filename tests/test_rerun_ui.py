"""UI: three Rerun buttons (Task 7).

Thin smoke tests over the served HTML/JS for the three Rerun affordances added
on top of Tasks 1-6's endpoints (``POST /api/run-rerun``,
``POST /api/investigation-rerun``, and the existing
``POST /api/study-run-baseline``):

  1. Sim DB row action (``static/sim-table.js`` ``_actions``) — a per-row
     ``↻ Rerun`` control wired to ``run-rerun``.
  2. Investigation header (``templates/index.html.j2``) — an
     ``#investigation-rerun`` button.
  3. Study-detail header — a "Rerun study" control (exercised indirectly via
     ``static/study-detail.js`` containing the wiring; the served-page
     assertion here focuses on the two pieces above, per the brief).

These are cheap "the wiring exists" checks against the live FastAPI app (via
``dashboard_client``), not exhaustive behavioral tests — behavior of the
endpoints themselves is covered by ``test_api_rerun.py``.
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


def test_index_html_has_investigation_rerun_button(dashboard_client, ws_copy):
    client = dashboard_client(workspace=ws_copy)
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="investigation-rerun"' in r.text


def test_sim_table_js_has_rerun_action(dashboard_client, ws_copy):
    client = dashboard_client(workspace=ws_copy)
    r = client.get("/sim-table.js")
    assert r.status_code == 200
    assert "run-rerun" in r.text
    assert "Rerun" in r.text

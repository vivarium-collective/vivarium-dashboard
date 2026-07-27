"""UI: Rerun/Reproduce buttons (Task 7, updated by Task 4).

Thin smoke tests over the served HTML/JS for the Rerun/Reproduce affordances:

  1. Sim DB row action (``static/sim-table.js`` ``_actions``) — a per-row
     ``↻ Rerun`` control. reproducible-rerun-spine Task 4 repointed this at
     ``POST /api/study-reproduce`` (manifest replay) instead of the generic
     ``/api/run-rerun`` — "Reproduce" vs "Run current spec" is now a
     deliberate, named distinction (see ``test_study_reproduce_button.py``).
  2. Investigation header (``templates/index.html.j2``) — an
     ``#investigation-rerun`` button (Task 4 relabeled it "Run current spec"
     — it still re-derives from each member study's current study.yaml via
     ``/api/investigation-rerun``; an investigation-level "Reproduce" is
     explicitly out of Task 4's scope, left for Task 7's DAG-ordered work).
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
    # Task 4: the per-row control now reproduces the recorded manifest via
    # /api/study-reproduce, not the generic /api/run-rerun.
    assert "study-reproduce" in r.text
    assert "Rerun" in r.text

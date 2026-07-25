"""The studies index (`GET /api/investigations`) reports a *display* status,
not the raw legacy ``status`` field: a stale ``status: running`` with no active
run must not read as "running" (it would mislabel the Studies-tab Status column
and pin the investigation to "Running now"). Only a genuine live run counts.
"""
from __future__ import annotations

import time
from pathlib import Path

import yaml

from vivarium_workbench.lib.investigations_index import build_investigations


def _study(ws: Path, name: str, **fields) -> None:
    p = ws / "studies" / name / "study.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(
        {"schema_version": 3, "name": name,
         "baseline": [{"composite": "x", "name": "b"}], **fields},
        sort_keys=False,
    ))


def _rows(ws: Path) -> dict:
    return {r["name"]: r for r in build_investigations(ws)["investigations"]}


def test_studies_index_demotes_stale_running(tmp_path):
    # Stale legacy `status: running`, no live run; real state is gate 'blocked'.
    ws = tmp_path / "ws"
    _study(ws, "s1", status="running", gate_status="blocked")
    assert _rows(ws)["s1"]["status"] == "blocked"


def test_studies_index_stale_running_no_axis_falls_to_planning(tmp_path):
    # Stale running with no multi-axis fallback → planning, never "running".
    ws = tmp_path / "ws"
    _study(ws, "s1", status="running")
    assert _rows(ws)["s1"]["status"] == "planning"


def test_studies_index_running_with_active_run(tmp_path):
    # A genuine active run (running row + fresh heartbeat) IS "running".
    ws = tmp_path / "ws"
    _study(ws, "s2", status="running",
           runs=[{"kind": "simulation", "status": "running", "heartbeat_at": time.time()}])
    assert _rows(ws)["s2"]["status"] == "running"

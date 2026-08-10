"""Tests for ``lib.composite_stop_views.stop_composite_run`` (issue #754).

Verifies the outcome→HTTP-status mapping and that the view resolves the run db
under ``<ws>/.pbg/composite-runs.db``. The signalling path is exercised end to
end in ``test_run_stop.py``; here ``os.killpg`` is monkeypatched so no real
process is ever signalled.
"""
from __future__ import annotations

import os
from pathlib import Path

from vivarium_workbench.lib import run_registry
from vivarium_workbench.lib import composite_stop_views as views
from vivarium_workbench.lib.composite_runs import (
    connect, save_metadata, complete_metadata, query_run_meta,
)


def _make_ws(tmp_path: Path) -> Path:
    (tmp_path / "workspace.yaml").write_text("name: demo-ws\n", encoding="utf-8")
    (tmp_path / ".pbg").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _db(ws: Path) -> Path:
    return ws / ".pbg" / "composite-runs.db"


def test_missing_run_id_400(tmp_path):
    ws = _make_ws(tmp_path)
    body, status = views.stop_composite_run(ws, "  ")
    assert status == 400
    assert body["error"] == "missing run_id"


def test_unknown_run_404(tmp_path):
    ws = _make_ws(tmp_path)
    connect(_db(ws)).close()  # empty db exists
    body, status = views.stop_composite_run(ws, "ghost")
    assert status == 404
    assert body["outcome"] == "not_found"


def test_running_run_is_signalled_and_cancelled_200(tmp_path, monkeypatch):
    ws = _make_ws(tmp_path)
    conn = connect(_db(ws))
    save_metadata(conn, spec_id="s", run_id="live", params={}, label="",
                  started_at=1.0, n_steps=5)
    conn.execute("UPDATE runs_meta SET pid=? WHERE run_id='live'", (os.getpid(),))
    conn.commit()
    conn.close()

    sent = []
    monkeypatch.setattr(run_registry.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(run_registry.os, "killpg",
                        lambda pgid, sig: sent.append((pgid, sig)))

    body, status = views.stop_composite_run(ws, "live")
    assert status == 200
    assert body["outcome"] == "signalled"
    assert len(sent) == 1
    conn = connect(_db(ws))
    assert query_run_meta(conn, run_id="live")["status"] == "cancelled"
    conn.close()


def test_already_finished_run_is_idempotent_200(tmp_path):
    ws = _make_ws(tmp_path)
    conn = connect(_db(ws))
    save_metadata(conn, spec_id="s", run_id="done", params={}, label="",
                  started_at=1.0, n_steps=5)
    complete_metadata(conn, run_id="done", n_steps=5, status="completed")
    conn.close()

    body, status = views.stop_composite_run(ws, "done")
    assert status == 200
    assert body["outcome"] == "already_terminal"
    assert body["status"] == "completed"

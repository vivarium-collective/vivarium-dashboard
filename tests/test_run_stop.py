"""Unit tests for stopping an in-flight detached composite run (issue #754).

A frozen run (e.g. ecoli_baseline whose memory climbs without finishing) could
previously only be recovered by force-quitting the whole Python process, losing
all run state and any chance at a stack trace. ``run_registry.stop_run`` sends a
signal to the detached run's process GROUP (SIGTERM by default, so the worker's
faulthandler dumps a traceback into its run.log before exiting) and marks the
run ``cancelled``.
"""
import os
import signal

import pytest

from vivarium_workbench.lib.composite_runs import (
    connect, save_metadata, complete_metadata, query_run_meta,
)
from vivarium_workbench.lib import run_registry


def _seed_running(db_file, run_id, pid):
    conn = connect(db_file)
    save_metadata(conn, spec_id="s", run_id=run_id, params={}, label="",
                  started_at=1.0, n_steps=5)
    if pid is not None:
        conn.execute("UPDATE runs_meta SET pid=? WHERE run_id=?", (pid, run_id))
        conn.commit()
    conn.close()


def test_stop_signals_live_run_and_marks_cancelled(tmp_path, monkeypatch):
    db_file = tmp_path / "runs.db"
    _seed_running(db_file, "live", os.getpid())  # our own pid — genuinely alive

    sent = []
    monkeypatch.setattr(run_registry.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(run_registry.os, "killpg",
                        lambda pgid, sig: sent.append((pgid, sig)))

    res = run_registry.stop_run(db_file, "live")

    assert res["outcome"] == "signalled"
    assert sent == [(os.getpid(), signal.SIGTERM)]
    conn = connect(db_file)
    assert query_run_meta(conn, run_id="live")["status"] == "cancelled"
    conn.close()


def test_stop_unknown_run_is_not_found(tmp_path, monkeypatch):
    db_file = tmp_path / "runs.db"
    _seed_running(db_file, "live", os.getpid())
    monkeypatch.setattr(run_registry.os, "killpg",
                        lambda *a: pytest.fail("must not signal an unknown run"))
    res = run_registry.stop_run(db_file, "ghost")
    assert res["outcome"] == "not_found"


def test_stop_already_terminal_is_idempotent_no_signal(tmp_path, monkeypatch):
    db_file = tmp_path / "runs.db"
    conn = connect(db_file)
    save_metadata(conn, spec_id="s", run_id="done", params={}, label="",
                  started_at=1.0, n_steps=5)
    complete_metadata(conn, run_id="done", n_steps=5, status="completed")
    conn.close()
    monkeypatch.setattr(run_registry.os, "killpg",
                        lambda *a: pytest.fail("must not signal a finished run"))
    res = run_registry.stop_run(db_file, "done")
    assert res["outcome"] == "already_terminal"
    assert res["status"] == "completed"
    conn = connect(db_file)
    assert query_run_meta(conn, run_id="done")["status"] == "completed"
    conn.close()


def test_stop_null_pid_marks_cancelled_without_signal(tmp_path, monkeypatch):
    db_file = tmp_path / "runs.db"
    _seed_running(db_file, "nopid", None)  # spawn never recorded a pid
    monkeypatch.setattr(run_registry.os, "killpg",
                        lambda *a: pytest.fail("no pid → nothing to signal"))
    res = run_registry.stop_run(db_file, "nopid")
    assert res["outcome"] == "no_pid"
    conn = connect(db_file)
    assert query_run_meta(conn, run_id="nopid")["status"] == "cancelled"
    conn.close()


def test_stop_dead_pid_marks_cancelled_without_signal(tmp_path, monkeypatch):
    db_file = tmp_path / "runs.db"
    _seed_running(db_file, "dead", 999_999)  # almost certainly not a live process
    monkeypatch.setattr(run_registry.os, "killpg",
                        lambda *a: pytest.fail("dead pid → do not signal"))
    res = run_registry.stop_run(db_file, "dead")
    assert res["outcome"] == "dead"
    conn = connect(db_file)
    assert query_run_meta(conn, run_id="dead")["status"] == "cancelled"
    conn.close()

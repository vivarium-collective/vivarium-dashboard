"""Process-lifecycle helpers for detached composite runs.

The dashboard server spawns runs via ``spawn_detached`` and reconciles
crash-orphaned rows via ``reconcile_stale_runs`` on startup. All read/write
goes through ``composite_runs`` — this module only deals with OS processes.

(Historical note: this module used to also carry a vendored ``runs_meta`` read
accessor — ``RUNS_META_DDL`` + ``latest_run`` — copied from
``viva_superpowers/run_registry.py``. That block was dead code once its only
caller, ``lib/backfill_runs.py``, was removed, so the Phase-2.1a DDL-drift
deferral is resolved by simply deleting it. The workbench's real ``runs_meta``
schema — including the ``manifest_json`` column the vendored copy lacked — is
owned and migrated by ``composite_runs`` (``connect``/``_migrate_runs_meta``).)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from vivarium_workbench.lib import composite_runs as cr

# Maximum simultaneous in-flight runs. POST returns 429 above this.
CONCURRENCY_CAP = 4


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID currently exists."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user — still 'alive' for our purposes.
        return True
    return True


def spawn_detached(request_path: Path, *, workspace: Path,
                   log_path: Path) -> int:
    """Launch `vivarium-dashboard run-composite` fully detached.

    ``start_new_session=True`` puts the child in its own process group so it
    survives a dashboard-server restart. stdout/stderr are redirected into
    ``log_path``. Returns the child PID.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "w")  # noqa: SIM115 — handed to the child, closed in finally
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen(
            [sys.executable, "-m", "vivarium_workbench.cli",
             "run-composite", "--request", str(request_path)],
            cwd=str(workspace),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    finally:
        log_fh.close()  # the child holds its own dup'd fd; the parent's copy is done
    return proc.pid


def reconcile_stale_runs(db_file: str | Path, workspace=None) -> int:
    """Mark every 'running' row whose process is gone as 'orphaned'.

    Called on server startup. A row with a NULL pid (spawn never recorded
    one) or a dead pid is orphaned; a live pid is left alone — that run
    genuinely survived the restart. Returns the count reconciled.

    ``workspace`` is threaded through to ``mark_orphaned`` so the terminal
    state also lands in the JSONL run log; the Simulations DB treats JSONL as
    authoritative, so a sqlite-only reconcile leaves the row reading "running".
    """
    db_file = Path(db_file)
    if not db_file.is_file():
        return 0
    conn = cr.connect(db_file)
    try:
        rows = conn.execute(
            "SELECT run_id, pid FROM runs_meta WHERE status='running'"
        ).fetchall()
        reconciled = 0
        for row in rows:
            pid = row["pid"]
            if pid is None or not _pid_alive(int(pid)):
                cr.mark_orphaned(conn, run_id=row["run_id"], workspace=workspace)
                reconciled += 1
        return reconciled
    finally:
        conn.close()


def count_running(db_file: str | Path) -> int:
    """Count rows currently in status='running'."""
    db_file = Path(db_file)
    if not db_file.is_file():
        return 0
    conn = cr.connect(db_file)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM runs_meta WHERE status='running'"
        ).fetchone()[0]
    finally:
        conn.close()

"""End-to-end test of the Composite Explorer's run-lifecycle API.

Spins up the dashboard server in-process against a fixture workspace and
exercises POST /api/composite-test-run and the three new GET endpoints.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
import socket
import subprocess

import pytest

_REPO_ROOT = Path(__file__).parent.parent

FIXTURE_WORKSPACE = _REPO_ROOT / "tests" / "_fixtures" / "ws_increase_demo"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def server(tmp_path):
    """Render a tiny fixture workspace and start the dashboard server."""
    if not FIXTURE_WORKSPACE.is_dir():
        pytest.skip(f"Fixture workspace not present at {FIXTURE_WORKSPACE}")
    # Copy fixture to tmp so writes (DB, reports) don't pollute the repo
    import shutil
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE_WORKSPACE, ws)
    port = _free_port()
    env = os.environ.copy()
    # The subprocess needs (a) vivarium_dashboard (already on its sys.path via
    # the venv install) and (b) the workspace's own package (pbg_ws_increase_demo).
    env["PYTHONPATH"] = str(ws) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "vivarium_dashboard.server",
         "--workspace", str(ws), "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env,
    )
    # Wait for the server-info file to appear (server writes it on bind)
    info_path = ws / ".pbg" / "server" / "server-info"
    for _ in range(40):
        if info_path.exists():
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        out, err = proc.communicate(timeout=2)
        pytest.fail(f"server did not start:\nstdout:\n{out.decode()}\n"
                    f"stderr:\n{err.decode()}")
    yield {"url": f"http://127.0.0.1:{port}", "ws": ws}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _post(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read().decode())


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def test_test_run_persists_and_returns_simulation_id(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    status, body = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {"rate": 2.5}, "steps": 5,
    })
    assert status == 200
    assert "simulation_id" in body
    assert body.get("steps") == 5
    # DB row exists
    db_file = server["ws"] / ".pbg" / "composite-runs.db"
    assert db_file.is_file()


def test_list_runs_includes_the_persisted_run(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {"rate": 2.5}, "steps": 5,
    })
    status, body = _get(f"{base}/api/composite-runs?"
                        f"spec_id={urllib.parse.quote(spec_id)}")
    assert status == 200
    runs = body["runs"]
    assert len(runs) >= 1
    assert runs[0]["status"] == "completed"
    assert runs[0]["n_steps"] >= 1
    # Verify the run actually produced trajectory rows in the SQLiteEmitter's table.
    import sqlite3
    db_path = server["ws"] / ".pbg" / "composite-runs.db"
    with sqlite3.connect(str(db_path)) as c:
        n = c.execute(
            "SELECT COUNT(*) FROM history WHERE simulation_id=?",
            (runs[0]["run_id"],),
        ).fetchone()[0]
    assert n >= 1, "expected SQLiteEmitter to have written history rows"


def test_fetch_single_run_trajectory(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    _, post_body = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {}, "steps": 4,
    })
    run_id = post_body["simulation_id"]
    status, body = _get(f"{base}/api/composite-run/{urllib.parse.quote(run_id)}")
    assert status == 200
    assert "trajectory" in body
    assert len(body["trajectory"]) >= 1


def test_fetch_state_at_step(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    _, post_body = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {}, "steps": 3,
    })
    run_id = post_body["simulation_id"]
    status, body = _get(
        f"{base}/api/composite-run/{urllib.parse.quote(run_id)}/state?step=1")
    assert status == 200
    assert "state" in body
    assert isinstance(body["state"], dict)


def test_distinct_runs_get_distinct_ids(server):
    base = server["url"]
    spec_id = "pbg_ws_increase_demo.composites.increase-demo"
    _, b1 = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {"rate": 1.0}, "steps": 2,
    })
    _, b2 = _post(f"{base}/api/composite-test-run", {
        "id": spec_id, "overrides": {"rate": 2.0}, "steps": 2,
    })
    assert b1["simulation_id"] != b2["simulation_id"]

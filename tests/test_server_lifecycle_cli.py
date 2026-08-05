"""Tests for the dashboard server-lifecycle ``vwb`` verbs
(``serve --detach`` + ``server-status`` / ``server-stop`` / ``server-open`` /
``server-restart``).

Phase 2.1j: these verbs replace ``viva_superpowers.workbench`` (the plugin's
1054-LOC server manager). They read/write ``<ws>/.pbg/server/{server-info,
server.pid}`` — exactly what foreground ``vwb serve`` already writes and what
every skill reads for the dashboard URL. Most cases exercise the lifecycle
against a dummy process (no full dashboard boot); one integration case boots a
real detached server against a fixture workspace.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from vivarium_workbench import cli


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text("schema_version: 2\nname: ws\n")
    return ws


def _write_server_info(ws, pid, url="http://127.0.0.1:59999"):
    d = ws / ".pbg" / "server"
    d.mkdir(parents=True, exist_ok=True)
    (d / "server-info").write_text(json.dumps({"pid": pid, "url": url}))
    (d / "server.pid").write_text(str(pid))


def _args(**kw):
    ns = type("NS", (), {})()
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


# --- pure helpers ----------------------------------------------------------

def test_investigation_url():
    assert cli._investigation_url("http://x/", None) == "http://x/"
    assert cli._investigation_url("http://x/", "my-inv") == "http://x/investigations/my-inv"


def test_pid_alive_true_false(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert cli._pid_alive(proc.pid) is True
        assert cli._pid_alive(999999999) is False
        assert cli._pid_alive(None) is False
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    assert cli._pid_alive(proc.pid) is False


# --- no-server behavior ----------------------------------------------------

def test_status_stopped_when_no_server(tmp_path, capsys):
    ws = _mk_ws(tmp_path)
    assert cli.cmd_server_status(_args(workspace=str(ws))) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "stopped"


def test_stop_not_running(tmp_path, capsys):
    ws = _mk_ws(tmp_path)
    assert cli.cmd_server_stop(_args(workspace=str(ws))) == 0
    assert "not running" in capsys.readouterr().out


def test_open_errors_when_not_running(tmp_path, capsys):
    ws = _mk_ws(tmp_path)
    assert cli.cmd_server_open(_args(workspace=str(ws), investigation=None)) == 1
    assert "not running" in capsys.readouterr().err


# --- lifecycle against a dummy process -------------------------------------

def test_status_running_pid_but_unreachable_is_stale(tmp_path, capsys):
    ws = _mk_ws(tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _write_server_info(ws, proc.pid)  # url:59999 is not actually serving
        assert cli.cmd_server_status(_args(workspace=str(ws))) == 0
        out = json.loads(capsys.readouterr().out)
        # pid alive but url not reachable -> stale
        assert out["state"] == "stale"
        assert out["pid"] == proc.pid
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_stop_kills_live_process_and_clears_state(tmp_path, capsys):
    ws = _mk_ws(tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    _write_server_info(ws, proc.pid)

    rc = cli.cmd_server_stop(_args(workspace=str(ws)))
    assert rc == 0
    assert f"stopped (pid {proc.pid})" in capsys.readouterr().out
    # process gone + state cleared
    proc.wait(timeout=5)
    assert cli._pid_alive(proc.pid) is False
    assert not (ws / ".pbg" / "server" / "server-info").exists()
    assert not (ws / ".pbg" / "server" / "server.pid").exists()


# --- real detached boot against a fixture workspace ------------------------

def _fixture_ws() -> Path | None:
    fx = Path(__file__).parent / "_fixtures"
    for d in sorted(fx.iterdir()) if fx.is_dir() else []:
        if (d / "workspace.yaml").exists():
            return d
    return None


def test_serve_detach_then_status_then_stop(tmp_path):
    """Boot a real detached server against a copy of a fixture workspace, then
    status (running) and stop."""
    # The dashboard can only boot when the full server stack imports — gate on
    # process_bigraph.artifacts, whose absence (a stale local process_bigraph)
    # is exactly what stops the server from starting in some dev venvs. CI has
    # the correct pinned process_bigraph, so this runs there.
    pytest.importorskip("process_bigraph.artifacts")
    src = _fixture_ws()
    if src is None:
        pytest.skip("no fixture workspace available")
    import shutil
    ws = tmp_path / "ws_copy"
    shutil.copytree(src, ws)
    # clear any stale server state from the fixture copy
    cli._clear_server_state(ws)

    try:
        rc = cli.cmd_serve(_args(
            workspace=str(ws), port=0, host="127.0.0.1", base_path="",
            detach=True, open=False, investigation=None,
            trust_proxy=False, allowed_origin=None,
        ))
        assert rc == 0
        # detach succeeded: server-info written + the detached server is alive.
        info = cli._read_server_info(ws)
        assert info and info.get("url")
        assert cli._pid_alive(cli._server_pid(ws)) is True
        # It should be reachable (running); poll a little in case boot is slow.
        import contextlib
        import io
        state = None
        for _ in range(200):  # ~20s margin
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cli.cmd_server_status(_args(workspace=str(ws)))
            state = json.loads(buf.getvalue())["state"]
            if state == "running":
                break
            time.sleep(0.1)
        assert state == "running", f"server never became reachable (last state={state})"
    finally:
        cli.cmd_server_stop(_args(workspace=str(ws)))
    # after stop, pid gone
    time.sleep(0.2)
    assert cli._pid_alive(cli._server_pid(ws) or 0) is False

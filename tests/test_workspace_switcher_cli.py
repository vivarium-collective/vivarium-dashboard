"""cmd_serve must register itself in the global running registry."""
from __future__ import annotations
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def pbg_home(tmp_path, monkeypatch):
    home = tmp_path / "pbg-home"
    monkeypatch.setenv("PBG_HOME", str(home))
    return home


@pytest.fixture
def workspace_dir(tmp_path):
    ws = tmp_path / "switcher-ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text(
        "name: switcher-ws\npackage: pbg_switcher_ws\n"
    )
    (ws / "reports").mkdir()
    return ws


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def test_cmd_serve_registers_on_boot(pbg_home, workspace_dir):
    """Spawning `vivarium-dashboard serve` should write ~/.pbg/servers/<name>.json
    within a few seconds, and remove it after we SIGTERM the process."""
    port = _free_port()
    env = {**os.environ, "PBG_HOME": str(pbg_home)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "vivarium_dashboard.cli",
         "serve", "--workspace", str(workspace_dir), "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        servers_dir = pbg_home / "servers"
        deadline = time.monotonic() + 8.0
        entry_path = None
        while time.monotonic() < deadline:
            if servers_dir.is_dir():
                cands = list(servers_dir.glob("switcher-ws*.json"))
                if cands:
                    entry_path = cands[0]
                    break
            time.sleep(0.1)
        assert entry_path is not None, "registration file never appeared"
        entry = json.loads(entry_path.read_text())
        assert entry["name"] == "switcher-ws"
        assert entry["path"] == str(workspace_dir.resolve())
        assert entry["pid"] == proc.pid
        assert entry["port"] == port
        assert entry["url"] == f"http://127.0.0.1:{port}"

        pid_file = workspace_dir / ".pbg" / "server" / "server.pid"
        assert pid_file.is_file()
        assert int(pid_file.read_text().strip()) == proc.pid
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    assert not entry_path.exists()
    pid_file = workspace_dir / ".pbg" / "server" / "server.pid"
    assert not pid_file.exists()

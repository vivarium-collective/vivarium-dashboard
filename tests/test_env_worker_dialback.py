"""The dial-back transport: a worker in its own pod connects back to us.

Same worker program, same JSON-RPC (spec §§6-11) — only the way the two ends
meet differs (REFACTOR-PLAN §2A.8). These tests spawn the real ``env_worker.py``
with ``--connect-to`` over loopback, which is the same code path a pod takes.

Weighted toward the handshake's negative paths: a listening socket that accepted
anything would be a hole in the workbench, and a rejected connection fails
*silently* from the caller's side unless asserted.
"""
import json
import os
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from vivarium_workbench.lib.env_worker_client import EnvWorker, EnvWorkerUnavailable
from vivarium_workbench.lib.env_worker_dialback import DialBackError, DialBackListener

WORKER = str(Path(__file__).resolve().parent.parent / "vivarium_workbench" / "env_worker.py")


def _spawn_dialing_worker(lst, workspace, *, token=None, log=subprocess.PIPE):
    """Spawn a worker the way a pod does: token via env, never on the command line.

    A command line is world-readable (``/proc/<pid>/cmdline``), so the token
    travels in the environment — which is also how viva-api will set it on the
    Job.
    """
    env = {**os.environ, "VIVARIUM_ENV_WORKER_TOKEN": token if token is not None else lst.token}
    return subprocess.Popen(
        [sys.executable, WORKER,
         "--connect-to", f"127.0.0.1:{lst.port}",
         "--workspace", str(workspace)],
        stdout=log, stderr=log, cwd=str(workspace), env=env,
    )


@pytest.fixture
def listener():
    lst = DialBackListener(bind_host="127.0.0.1")
    yield lst
    lst.close_listener()


# --- the happy path: identical protocol over a different transport -----------

def test_worker_dials_back_and_speaks_the_same_protocol(listener, tmp_path):
    proc = _spawn_dialing_worker(listener, tmp_path)
    try:
        sock = listener.accept(timeout=30)
        with EnvWorker.from_socket(sock, tmp_path) as w:
            info = w.call("initialize")
            assert info["protocol_version"]
            r = w.call("ping")
            assert r["ok"] is True and r["uptime_s"] >= 0
    finally:
        proc.kill(); proc.wait(timeout=10)


def test_remote_worker_close_does_not_try_to_reap_a_process(listener, tmp_path):
    """``from_socket`` has no subprocess — closing must not blow up looking for one."""
    proc = _spawn_dialing_worker(listener, tmp_path)
    try:
        w = EnvWorker.from_socket(listener.accept(timeout=30), tmp_path)
        assert w.alive() is True
        w.close()
        w.close()                  # idempotent, as for the local transport
        assert w.alive() is False  # socket dropped => honest liveness
        # A late call on a closed worker is the protocol's own error, not an
        # AttributeError from a None socket — this is what makes close()
        # re-entrant for a transport with no subprocess to fall back on.
        with pytest.raises(EnvWorkerUnavailable, match="closed"):
            w.call("ping")
    finally:
        proc.kill(); proc.wait(timeout=10)


# --- handshake: the part that guards a listening port -----------------------

def test_wrong_token_is_refused_before_any_protocol(listener, tmp_path):
    proc = _spawn_dialing_worker(listener, tmp_path, token="not-the-token")
    try:
        with pytest.raises(DialBackError, match="token mismatch"):
            listener.accept(timeout=30)
    finally:
        proc.kill(); proc.wait(timeout=10)


def test_connection_that_sends_nothing_is_refused():
    lst = DialBackListener(bind_host="127.0.0.1")
    try:
        c = socket.create_connection(("127.0.0.1", lst.port))
        c.close()                                   # connect, then vanish
        with pytest.raises(DialBackError, match="closed before the handshake"):
            lst.accept(timeout=10)
    finally:
        lst.close_listener()


def test_malformed_handshake_is_refused():
    lst = DialBackListener(bind_host="127.0.0.1")
    try:
        def dial():
            c = socket.create_connection(("127.0.0.1", lst.port))
            body = b"{not json"
            c.sendall(struct.pack(">I", len(body)) + body)
        threading.Thread(target=dial, daemon=True).start()
        with pytest.raises(DialBackError, match="malformed handshake"):
            lst.accept(timeout=10)
    finally:
        lst.close_listener()


def test_oversized_handshake_frame_is_refused_without_allocating():
    lst = DialBackListener(bind_host="127.0.0.1")
    try:
        def dial():
            c = socket.create_connection(("127.0.0.1", lst.port))
            c.sendall(struct.pack(">I", 500 * 1024 * 1024))   # claim 500 MiB
        threading.Thread(target=dial, daemon=True).start()
        with pytest.raises(DialBackError, match="too large"):
            lst.accept(timeout=10)
    finally:
        lst.close_listener()


def test_token_absent_from_the_handshake_is_refused():
    lst = DialBackListener(bind_host="127.0.0.1")
    try:
        def dial():
            c = socket.create_connection(("127.0.0.1", lst.port))
            body = json.dumps({"hello": "world"}).encode()
            c.sendall(struct.pack(">I", len(body)) + body)
        threading.Thread(target=dial, daemon=True).start()
        with pytest.raises(DialBackError, match="token mismatch"):
            lst.accept(timeout=10)
    finally:
        lst.close_listener()


# --- lifecycle --------------------------------------------------------------

def test_no_worker_within_timeout_is_a_clear_error(listener):
    with pytest.raises(DialBackError, match="no worker connected"):
        listener.accept(timeout=0.4)


def test_listener_stops_accepting_after_one_worker(listener, tmp_path):
    """One listener, one worker: the port must not stay open for a second peer."""
    proc = _spawn_dialing_worker(listener, tmp_path)
    try:
        sock = listener.accept(timeout=30)
        with pytest.raises((ConnectionRefusedError, OSError)):
            socket.create_connection(("127.0.0.1", listener.port), timeout=2)
        sock.close()
    finally:
        proc.kill(); proc.wait(timeout=10)


def test_minted_token_is_argv_safe():
    """A token starting with "-" is parsed as an option flag by any argv consumer.

    ``token_urlsafe`` produces one about 2% of the time, which reads as a flaky
    cluster rather than a bug. Hex has no such character.
    """
    for _ in range(200):
        lst = DialBackListener(bind_host="127.0.0.1")
        try:
            assert not lst.token.startswith("-")
            assert lst.token.isalnum()
        finally:
            lst.close_listener()


def test_each_listener_mints_its_own_token():
    a, b = DialBackListener(bind_host="127.0.0.1"), DialBackListener(bind_host="127.0.0.1")
    try:
        assert a.token != b.token and len(a.token) >= 32
        assert a.port != b.port
    finally:
        a.close_listener(); b.close_listener()


# --- the worker's own argument contract -------------------------------------

def test_worker_requires_a_transport(tmp_path):
    r = subprocess.run([sys.executable, WORKER, "--workspace", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "--socket-fd" in r.stderr and "--connect-to" in r.stderr


def test_worker_refuses_dial_back_without_a_token(tmp_path):
    r = subprocess.run([sys.executable, WORKER, "--connect-to", "127.0.0.1:1",
                        "--workspace", str(tmp_path)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode != 0
    assert "token" in r.stderr.lower()

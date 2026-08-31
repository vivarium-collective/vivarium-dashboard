"""The worker must not die 30 seconds after its last call.

Measured on dev: a worker with no traffic exited at **30 s to the second**, with
an unhandled `TimeoutError` out of `_recv_exact` and a pod in `Error`.

The cause was not a reaper. `_dial_back` used
`socket.create_connection(..., timeout=30.0)`, and that timeout applies to the
socket's **whole life**, not just the connect — so `_serve`'s blocking recv
inherited it as an accidental idle deadline. `--connect-timeout` was bounding
every idle gap for the worker's entire session.

This pins both halves of the fix: the connect timeout does not leak, and the
idle policy that replaces it is deliberate, generous, and — the part §E asked
about — **never fires while a call is in flight**.
"""

from __future__ import annotations

import socket
import struct
import threading
from typing import Any

import pytest

import vivarium_workbench.env_worker as ew


def _pair() -> tuple[socket.socket, socket.socket]:
    a, b = socket.socketpair()
    return a, b


def _frame(obj: dict[str, Any]) -> bytes:
    import json

    body = json.dumps(obj).encode()
    return struct.pack(">I", len(body)) + body


def _read_reply(sock: socket.socket) -> dict[str, Any]:
    import json

    hdr = b""
    while len(hdr) < 4:
        hdr += sock.recv(4 - len(hdr))
    (n,) = struct.unpack(">I", hdr)
    body = b""
    while len(body) < n:
        body += sock.recv(n - len(body))
    return json.loads(body)  # type: ignore[no-any-return]


# --- the bug: a connect timeout must not become an idle deadline ------------


def test_dial_back_clears_the_connect_timeout() -> None:
    """The regression proper. If `create_connection`'s timeout survives, every
    idle gap longer than it kills the worker."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    accepted: list[socket.socket] = []

    def _accept() -> None:
        conn, _ = listener.accept()
        conn.recv(4096)  # the handshake frame
        accepted.append(conn)

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    sock = ew._dial_back(f"127.0.0.1:{port}", "tok", 5.0)
    t.join(timeout=5)
    try:
        assert sock.gettimeout() is None, (
            "the connect timeout is still on the socket; it will fire as an idle "
            "deadline in _serve and kill the worker mid-session"
        )
    finally:
        sock.close()
        for c in accepted:
            c.close()
        listener.close()


# --- the replacement policy -------------------------------------------------


def test_an_idle_worker_exits_cleanly_rather_than_crashing() -> None:
    """Reaping is a decision, not a fault. The old behaviour surfaced as an
    unhandled traceback and a pod in `Error`, which reads as something broken
    rather than as a worker that was no longer needed."""
    ours, theirs = _pair()
    done: list[bool] = []

    def _serve() -> None:
        ew._serve(theirs, idle_timeout=0.25)
        done.append(True)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    t.join(timeout=5)
    assert done == [True], "an idle worker should RETURN, not raise"
    ours.close()
    theirs.close()


def test_a_slow_call_is_not_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """§E's actual question: "what must the idle reaper know so it does not reap
    a worker mid-job?" The answer is that idleness is the gap BETWEEN frames.
    A method that takes longer than the idle timeout must still complete."""
    import time as _time

    monkeypatch.setitem(
        ew.__dict__, "_handle", lambda method, params: (_time.sleep(0.6), {"ok": True})[1]
    )
    ours, theirs = _pair()
    t = threading.Thread(target=lambda: ew._serve(theirs, idle_timeout=0.2), daemon=True)
    t.start()
    ours.sendall(_frame({"jsonrpc": "2.0", "id": 1, "method": "slow", "params": {}}))
    reply = _read_reply(ours)
    assert reply["result"] == {"ok": True}, "a 0.6s call died under a 0.2s idle timeout"
    ours.close()
    theirs.close()


def test_zero_disables_the_idle_timeout() -> None:
    """A deployment that wants a worker to wait indefinitely must be able to say
    so; the flag maps 0 to None rather than to an instant reap."""
    import inspect

    source = inspect.getsource(ew.main)
    assert "if args.idle_timeout > 0 else None" in source


def test_the_default_matches_the_documented_pool_ttl() -> None:
    """Both transports should agree on what idle means. 900s is
    ENV_WORKER_IDLE_TTL in env-worker-runtime.md; 30s never was."""
    import inspect

    source = inspect.getsource(ew.main)
    assert '"900"' in source
    assert "VIVARIUM_ENV_WORKER_IDLE_TIMEOUT" in source


def test_a_normal_call_still_works_with_an_idle_timeout_set() -> None:
    """The timeout must be cleared and re-armed around each frame, not left on."""
    ours, theirs = _pair()
    t = threading.Thread(target=lambda: ew._serve(theirs, idle_timeout=5.0), daemon=True)
    t.start()
    ours.sendall(_frame({"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}}))
    reply = _read_reply(ours)
    assert reply["id"] == 7
    assert reply["result"]["ok"] is True
    ours.close()
    theirs.close()

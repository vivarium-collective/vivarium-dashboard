"""Env-worker **dial-back** transport — the cloud adapter's connection seam.

The local adapter (``env_worker_client.EnvWorker``) spawns a subprocess over a
``socket.socketpair()``. A hosted worker cannot be spawned that way: it runs in
its own pod, from the simulator's own image, created by viva-api (see
REFACTOR-PLAN §2A.8 / vivarium-workbench#942). This module supplies the piece
that differs — *how the two ends meet* — and nothing else.

**The worker dials back.** The workbench listens on an ephemeral port and the
worker connects to it, rather than the workbench connecting to the worker. Two
reasons, both structural rather than stylistic:

* viva-api's service account may create **Jobs**, but not Services — so a worker
  pod has no stable DNS name to dial. The alternative is reading
  ``status.podIP``, which needs pod-get on the *workbench* side and races pod
  scheduling.
* It keeps the workbench free of any cluster API access at all, which §2B.2
  requires (viva-api owns every credential).

**The message layer is untouched.** Spec §§6-11 — JSON-RPC, framing, the method
catalog — are transport-independent by design (§2: "the message schema is the
contract; the transport is an adapter"). ``accept()`` hands back a plain
connected socket that ``EnvWorker.from_socket`` drives with exactly the same
code the socketpair uses.

**A listening port is an attack surface**, so the handshake is not optional: the
worker's first frame must carry the one-time token this listener minted, and a
connection that sends anything else is closed without ever reaching the
protocol. The token travels to the worker out-of-band (viva-api puts it in the
Job's env), never over this socket in the clear before it is checked.
"""
from __future__ import annotations

import json
import secrets
import socket
import struct

__all__ = ["DialBackListener", "DialBackError", "HANDSHAKE_FRAME_CAP"]

# The handshake frame is a fixed shape; anything larger is a bad actor or a
# protocol mismatch, and is rejected before allocation.
HANDSHAKE_FRAME_CAP = 4096


class DialBackError(Exception):
    """No worker connected, or the one that connected failed the handshake."""


class DialBackListener:
    """Listen for exactly one worker to dial back.

    Usage mirrors the lifetime of a single worker::

        with DialBackListener() as lst:
            start_worker(host=..., port=lst.port, token=lst.token)
            sock = lst.accept(timeout=300)
            worker = EnvWorker.from_socket(sock, workspace)

    ``bind_host`` defaults to ``0.0.0.0`` because in-cluster the worker reaches
    the workbench by pod IP; tests and local runs pass ``127.0.0.1``.
    """

    def __init__(self, *, bind_host: str = "0.0.0.0", token: str | None = None,
                 advertise_host: str | None = None):
        # token_hex, NOT token_urlsafe: the base64url alphabet contains "-", and
        # a token that happens to START with one is parsed as an option flag by
        # any argv-based consumer — an intermittent ~2% spawn failure that would
        # look like a cluster problem. Hex is alphanumeric, so the class is gone.
        self.token = token or secrets.token_hex(32)
        self.advertise_host = advertise_host
        self._sock: socket.socket | None = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((bind_host, 0))          # port 0 → kernel picks a free one
        self._sock.listen(1)                     # one worker, one connection
        self.port = self._sock.getsockname()[1]

    def accept(self, timeout: float = 300.0) -> socket.socket:
        """Block until a worker connects and proves the token; return its socket.

        ``timeout`` covers pod scheduling and image pull, so it is generous and
        deliberately separate from the per-call timeout in ``EnvWorker``.
        """
        if self._sock is None:
            raise DialBackError("listener is closed")
        self._sock.settimeout(timeout)
        try:
            conn, _peer = self._sock.accept()
        except socket.timeout:
            raise DialBackError(
                f"no worker connected within {timeout}s") from None
        except OSError as e:
            raise DialBackError(f"accept failed: {e}") from e

        try:
            self._verify(conn, timeout)
        except Exception:
            conn.close()
            raise
        # One worker per listener: stop listening so the port cannot be reused
        # by a second connection while this worker is live.
        self.close_listener()
        return conn

    def _verify(self, conn: socket.socket, timeout: float) -> None:
        conn.settimeout(timeout)
        hdr = _recv_exact(conn, 4)
        if hdr is None:
            raise DialBackError("worker closed before the handshake")
        (n,) = struct.unpack(">I", hdr)
        if n > HANDSHAKE_FRAME_CAP:
            raise DialBackError(f"handshake frame too large: {n} bytes")
        body = _recv_exact(conn, n)
        if body is None:
            raise DialBackError("worker closed mid-handshake")
        try:
            msg = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise DialBackError(f"malformed handshake: {e}") from e

        offered = msg.get("token") if isinstance(msg, dict) else None
        # Constant-time: a timing oracle on a token is a real, if unglamorous,
        # way to lose one.
        if not isinstance(offered, str) or not secrets.compare_digest(offered, self.token):
            raise DialBackError("handshake token mismatch")

    def close_listener(self) -> None:
        """Stop accepting. The already-accepted connection is unaffected."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self) -> "DialBackListener":
        return self

    def __exit__(self, *exc) -> None:
        self.close_listener()


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout:
            raise DialBackError("handshake timed out") from None
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)

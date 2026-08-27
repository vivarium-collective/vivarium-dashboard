"""Warm env-worker pool — the `EnvironmentResolver`'s worker lifecycle
(env-worker-protocol.md §17).

Keeps warm env workers keyed by `(workspace, interpreter)` so a session's repeated
env queries **reuse one worker** — paying `build_core` once, not per request. This
is not an optimization: `build_core` is ~15 s on v2ecoli (measured), so a
spawn-per-query design would put ~15 s on every composite / registry request. The
pool is what makes the route migrations viable.

Policy (protocol §17): **lazy spawn** (a worker starts on first use), **idle-TTL
eviction** (a worker idle past `T_idle` is reaped), and a **global LRU cap** `K`
(admitting the K+1-th worker evicts the least-recently-used). `T_idle` and `K` are
runtime config. Eviction frees the **process**; the venv (workspace-store §8) and
its GC are separate.

**Slice scope:** the pool + eviction, standalone and tested. It is not yet wired
into `WorkspaceContext` / the routes (that's the next slices), so this is additive
and behavior-preserving. Keying is `(workspace, interpreter)` today; it becomes the
environment coordinate once materialization lands.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from vivarium_workbench.lib.env_compat import get_env

logger = logging.getLogger(__name__)
from vivarium_workbench.lib.env_worker_client import EnvWorker, EnvWorkerUnavailable
from vivarium_workbench.lib.env_worker_routing import is_job_class

if TYPE_CHECKING:  # launchers import the pool's callers; keep it type-only
    from vivarium_workbench.lib.env_worker_launcher import WorkerLauncher


def _int_env(name: str, default: int) -> int:
    try:
        v = get_env(name, str(default))
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_close(worker: EnvWorker) -> None:
    try:
        worker.close()
    except Exception:  # noqa: BLE001 — eviction must never raise
        pass


class _Entry:
    __slots__ = ("worker", "last_used")

    def __init__(self, worker: EnvWorker):
        self.worker = worker
        self.last_used = time.monotonic()


class WorkerPool:
    """A bounded pool of warm env workers keyed by ``(workspace, interpreter)``."""

    def __init__(self, *, max_workers: int | None = None, idle_ttl: float | None = None,
                 call_timeout: float | None = None, launcher=None):
        # HOW a worker is created is the launcher's business; the pool owns only
        # WHEN (lazy spawn, idle-TTL eviction, LRU cap). Local subprocess or
        # remote image-as-worker is one deployment-wide decision made at the
        # composition root — see env_worker_launcher.default_launcher (§2A.8).
        # Defaults to local so existing callers and tests are unchanged.
        # `launcher`, when given, is used for EVERY method (tests, and any caller
        # that wants one explicit transport). When it is None the pool routes per
        # method — see _launcher_for and §2A.8 workstream 8.
        self._launcher: WorkerLauncher | None = launcher
        self._local_launcher: WorkerLauncher | None = None
        self._deployment_launcher: WorkerLauncher | None = None
        self._warned: set[tuple[str, str]] = set()
        # K and T_idle (seconds), config-overridable (plan §G).
        self.max_workers = max_workers if max_workers is not None else _int_env("ENV_WORKER_POOL_MAX", 8)
        self.idle_ttl = idle_ttl if idle_ttl is not None else _int_env("ENV_WORKER_IDLE_TTL", 900)
        # Per-call socket timeout (seconds). 60s suits interactive calls, but a
        # long baseline (e.g. a multi-generation ecoli_baseline, default 2700
        # steps, ~minutes) dispatched through the pool would exceed it and trip
        # EnvWorkerUnavailable → one respawn → fail. Config-overridable so such
        # workloads can raise it; default unchanged (backward-compatible).
        self.call_timeout = call_timeout if call_timeout is not None else _int_env("ENV_WORKER_CALL_TIMEOUT", 60)
        self._entries: dict[tuple[str, str, str], _Entry] = {}
        self._lock = threading.Lock()

    # -- public -------------------------------------------------------------
    def call(self, workspace, method: str, params: dict | None = None,
             *, interpreter: str | None = None) -> dict:
        """Query the warm worker for this environment. On a worker that died or
        was evicted mid-flight, drop it and respawn once (protocol §9).

        When ``interpreter`` is not given, the LAUNCHER names the environment
        (``env_key``): the workspace's own interpreter for a local worker, the
        image's commit for a remote one. Order matters — resolving an interpreter
        first asks a venv-less workspace a question the remote path never needed
        answered, and under REQUIRE_WORKSPACE_VENV that raises instead of routing.
        """
        ws = str(Path(workspace))
        launcher = self._launcher_for(method, ws)
        interp = interpreter or launcher.env_key(ws)
        try:
            return self._acquire(ws, interp, launcher).call(method, params)
        except EnvWorkerUnavailable:
            self._drop(ws, interp, launcher.kind)
            return self._acquire(ws, interp, launcher).call(method, params)

    def _launcher_for(self, method: str, ws: str):
        """Interactive methods follow the deployment; job-class methods stay local.

        §2A.7 puts simulations and heavy analyses in a *job*, not a worker call, and
        a hosted worker pod is sized for interaction (2 GiB). Routing a study that
        declares 1000 seeds x 10 generations there is an OOMKill, so job-class
        methods keep today's local subprocess even on a hosted deployment.

        That is deliberately NOT a refusal: a small study run locally is a
        legitimate hosted use case, and the scale precheck that could tell small
        from large is step 2 of the design. Until then this logs once per
        (method, workspace) so the gap is discoverable rather than silent -- the
        failure backlog item 18 already recorded once, on this same path.
        """
        if self._launcher is not None:
            return self._launcher
        from vivarium_workbench.lib.env_worker_launcher import (
            LocalWorkerLauncher, default_launcher)
        if is_job_class(method):
            if self._local_launcher is None:
                self._local_launcher = LocalWorkerLauncher()
            if self._deployment_kind() == "remote" and (method, ws) not in self._warned:
                self._warned.add((method, ws))
                logger.warning(
                    "%s runs in a LOCAL worker on a deployment configured for remote "
                    "env workers. Small runs are fine; anything at deployment scale "
                    "should dispatch to viva-api instead (see remote_pinned."
                    "resolve_run_target / remote_run_views.remote_run_submit). "
                    "REFACTOR-PLAN §2A.8 workstream 8.", method)
            return self._local_launcher
        if self._deployment_launcher is None:
            self._deployment_launcher = default_launcher()
        return self._deployment_launcher

    def _deployment_kind(self) -> str:
        from vivarium_workbench.lib.env_worker_launcher import default_launcher
        if self._deployment_launcher is None:
            self._deployment_launcher = default_launcher()
        return getattr(self._deployment_launcher, "kind", "local")

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def discard(self, workspace, *, interpreter: str | None = None) -> None:
        """Evict this environment's worker(s) (e.g. on a session switch).

        Drops every worker for the workspace, whatever its environment key: methods
        route per class, so one workspace can hold a remote worker (interactive) and
        a local one (job-class) at once, and a switch must not leave either behind.

        Matching on the workspace alone — rather than reconstructing the key — is
        what makes that reliable. The keys are the launchers' to mint (a resolved
        interpreter, an image commit); guessing one here missed them and quietly
        left warm workers pinned to the old session.
        """
        ws = str(Path(workspace))
        with self._lock:
            keys = [k for k in self._entries
                    if k[0] == ws and (interpreter is None or k[1] == interpreter)]
        for key in keys:
            self._drop(*key)

    def close_all(self) -> None:
        with self._lock:
            workers = [e.worker for e in self._entries.values()]
            self._entries.clear()
        for w in workers:
            _safe_close(w)

    # -- internals ----------------------------------------------------------
    def _acquire(self, ws: str, interp: str, launcher) -> EnvWorker:
        # Keyed by kind as well: a local and a remote worker for the same
        # (workspace, interpreter) are DIFFERENT environments and must never
        # share a pool entry.
        key = (ws, interp, launcher.kind)
        to_close: list[EnvWorker] = []
        with self._lock:
            to_close.extend(self._reap_idle_locked())
            entry = self._entries.get(key)
            if entry is not None and entry.worker.alive():
                entry.last_used = time.monotonic()
                worker = entry.worker
            else:
                if entry is not None:                      # a dead worker under this key
                    to_close.append(self._entries.pop(key).worker)
                while len(self._entries) >= self.max_workers and self._entries:
                    to_close.append(self._pop_lru_locked())  # LRU cap (protocol §17)
                # lazy spawn (local: Popen is ~ms; remote: a pod dialling back —
                # build_core is on the first call either way)
                worker = launcher.launch(ws, interpreter=interp, timeout=self.call_timeout)
                self._entries[key] = _Entry(worker)
        for w in to_close:
            _safe_close(w)
        return worker

    def _drop(self, ws: str, interp: str, kind: str = "local") -> None:
        with self._lock:
            entry = self._entries.pop((ws, interp, kind), None)
        if entry is not None:
            _safe_close(entry.worker)

    def _reap_idle_locked(self) -> list[EnvWorker]:
        now = time.monotonic()
        stale = [k for k, e in self._entries.items() if now - e.last_used > self.idle_ttl]
        return [self._entries.pop(k).worker for k in stale]

    def _pop_lru_locked(self) -> EnvWorker:
        lru_key = min(self._entries, key=lambda k: self._entries[k].last_used)
        return self._entries.pop(lru_key).worker


# ---------------------------------------------------------------------------
# Process-wide singleton (a later slice binds per-session workers through this).
# ---------------------------------------------------------------------------
_pool: WorkerPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> WorkerPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = WorkerPool()
                # Graceful shutdown on process exit. (Workers also self-terminate
                # when the parent's socket EOFs, so a hard kill still leaks nothing.)
                import atexit
                atexit.register(_pool.close_all)
    return _pool

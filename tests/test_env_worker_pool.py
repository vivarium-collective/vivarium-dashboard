"""Warm env-worker pool (env-worker-protocol.md §17): reuse, isolation, LRU cap,
idle-TTL eviction, crash-respawn. Uses bare tmp workspaces — initialize/ping need
no workspace package, so these are fast and env-independent."""
import time

import pytest

from vivarium_workbench.lib.env_worker_pool import WorkerPool


@pytest.fixture
def pool():
    p = WorkerPool(max_workers=2, idle_ttl=1000)
    yield p
    p.close_all()


def _pid(pool, ws):
    return pool.call(ws, "initialize")["pid"]


def test_reuse_keeps_one_warm_worker(pool, tmp_path):
    """Repeated calls to one workspace reuse ONE worker — build_core is paid once."""
    pid1 = _pid(pool, tmp_path)
    pid2 = _pid(pool, tmp_path)
    assert pid1 == pid2            # same warm process
    assert pool.size() == 1


def test_distinct_workspaces_get_distinct_workers(pool, tmp_path):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    assert _pid(pool, a) != _pid(pool, b)
    assert pool.size() == 2


def test_lru_cap_evicts_least_recently_used(tmp_path):
    p = WorkerPool(max_workers=2, idle_ttl=1000)
    try:
        a = tmp_path / "a"; a.mkdir()
        b = tmp_path / "b"; b.mkdir()
        c = tmp_path / "c"; c.mkdir()
        pid_a = _pid(p, a)
        _pid(p, b)
        _pid(p, a)                 # touch a -> b is now the LRU
        _pid(p, c)                 # admits c (3rd) -> evicts b
        assert p.size() == 2
        assert _pid(p, a) == pid_a  # a still warm (same pid)
    finally:
        p.close_all()


def test_idle_ttl_eviction(tmp_path):
    p = WorkerPool(max_workers=8, idle_ttl=0.3)
    try:
        a = tmp_path / "a"; a.mkdir()
        b = tmp_path / "b"; b.mkdir()
        _pid(p, a)
        time.sleep(0.5)            # a goes idle past the TTL
        _pid(p, b)                 # the acquire sweep reaps the idle a
        assert p.size() == 1
    finally:
        p.close_all()


def test_crashed_worker_is_respawned(pool, tmp_path):
    pid1 = _pid(pool, tmp_path)
    # reach in and kill the warm worker's process
    (entry,) = list(pool._entries.values())
    entry.worker._proc.kill()
    entry.worker._proc.wait(timeout=5)
    pid2 = _pid(pool, tmp_path)     # pool drops the dead one + respawns
    assert pid2 != pid1
    assert pool.size() == 1


def test_discard_evicts(pool, tmp_path):
    _pid(pool, tmp_path)
    assert pool.size() == 1
    pool.discard(tmp_path)
    assert pool.size() == 0


def test_call_timeout_default_config_and_override(monkeypatch):
    # Default 60s (backward-compatible); constructor + env var override.
    assert WorkerPool().call_timeout == 60
    assert WorkerPool(call_timeout=1800).call_timeout == 1800
    # get_env reads the VIVARIUM_WORKBENCH_-prefixed name (as the other knobs do).
    monkeypatch.setenv("VIVARIUM_WORKBENCH_ENV_WORKER_CALL_TIMEOUT", "900")
    assert WorkerPool().call_timeout == 900


def test_pool_passes_call_timeout_to_envworker(monkeypatch, tmp_path):
    # The pool must thread its call_timeout into each spawned EnvWorker so long
    # baselines don't trip the default 60s socket timeout.
    captured = {}

    class _FakeWorker:
        def __init__(self, ws, *, interpreter=None, timeout=None):
            captured["timeout"] = timeout
        def alive(self):
            return True
        def call(self, method, params=None):
            return {"ok": True}
        def close(self):
            pass

    # Patched on the LAUNCHER, which is where workers are now constructed: the
    # pool owns when a worker is created, env_worker_launcher owns how (local
    # subprocess vs remote image-as-worker, §2A.8). The property under test is
    # unchanged — call_timeout must reach the worker — and this still exercises
    # the real pool -> launcher -> EnvWorker chain rather than stubbing it out.
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_launcher.EnvWorker", _FakeWorker)
    p = WorkerPool(call_timeout=1234)
    p.call(tmp_path, "ping", interpreter="/usr/bin/python3")
    assert captured["timeout"] == 1234

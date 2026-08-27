"""Method-class routing at the pool — §2A.8 workstream 8 step 1.

The pool is the one choke point all 25 `get_pool()` call sites pass through, and
it already sees the method name. These tests pin the property that makes that
worth doing: **a job-class method cannot reach a remote worker**, whatever the
deployment is configured for and whichever call site issued it.
"""
import re
from pathlib import Path

import pytest

from vivarium_workbench.lib.env_worker_pool import WorkerPool
from vivarium_workbench.lib.env_worker_routing import JOB_CLASS_METHODS, is_job_class


class _FakeWorker:
    def __init__(self, kind):
        self.kind = kind

    def alive(self):
        return True

    def call(self, method, params=None):
        return {"served_by": self.kind, "method": method}

    def close(self):
        pass


class _FakeLauncher:
    def __init__(self, kind):
        self.kind = kind
        self.launched = 0

    def launch(self, workspace, *, interpreter, timeout):
        self.launched += 1
        return _FakeWorker(self.kind)


@pytest.fixture
def routed(monkeypatch):
    """A pool with per-method routing and both launchers faked."""
    local, remote = _FakeLauncher("local"), _FakeLauncher("remote")
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_launcher.LocalWorkerLauncher", lambda: local)
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_launcher.default_launcher", lambda: remote)
    return WorkerPool(), local, remote


# --- the property worth having ----------------------------------------------

@pytest.mark.parametrize("method", sorted(JOB_CLASS_METHODS))
def test_job_class_methods_never_reach_a_remote_worker(routed, tmp_path, method):
    """A worker pod is sized for interaction (2 GiB). A study on this system
    declares 1000 seeds x 10 generations — that must not land there."""
    pool, local, remote = routed
    r = pool.call(tmp_path, method, interpreter="/usr/bin/python3")
    assert r["served_by"] == "local"
    assert remote.launched == 0


@pytest.mark.parametrize("method", ["registry_catalog", "discover_composites",
                                    "attach_process_docs", "list_generators"])
def test_interactive_methods_follow_the_deployment(routed, tmp_path, method):
    pool, local, remote = routed
    r = pool.call(tmp_path, method, interpreter="/usr/bin/python3")
    assert r["served_by"] == "remote"


def test_one_workspace_can_hold_both_kinds_at_once(routed, tmp_path):
    """Keyed by kind: a local and a remote worker for the same (ws, interpreter)
    are different environments and must not share a pool entry."""
    pool, local, remote = routed
    assert pool.call(tmp_path, "registry_catalog", interpreter="/x")["served_by"] == "remote"
    assert pool.call(tmp_path, "run_study", interpreter="/x")["served_by"] == "local"
    assert pool.size() == 2
    assert (local.launched, remote.launched) == (1, 1)


def test_discard_evicts_both_kinds(routed, tmp_path):
    """A session switch must not leave the other kind behind."""
    pool, local, remote = routed
    pool.call(tmp_path, "registry_catalog", interpreter="/x")
    pool.call(tmp_path, "run_study", interpreter="/x")
    assert pool.size() == 2
    pool.discard(tmp_path, interpreter="/x")
    assert pool.size() == 0


def test_an_explicit_launcher_still_overrides_everything(tmp_path):
    """Tests and single-transport callers keep the old behaviour."""
    only = _FakeLauncher("local")
    pool = WorkerPool(launcher=only)
    for m in ("registry_catalog", "run_study"):
        assert pool.call(tmp_path, m, interpreter="/x")["served_by"] == "local"


# --- drift guard -------------------------------------------------------------

def test_every_declared_capability_is_accounted_for():
    """A newly added HEAVY method must fail this test rather than silently
    inheriting the interactive path."""
    src = (Path(__file__).resolve().parent.parent
           / "vivarium_workbench" / "env_worker.py").read_text()
    caps = {c.strip().strip('"') for c in
            re.search(r"_CAPABILITIES = \[(.*?)\]", src, re.S).group(1).replace("\n", "").split(",")
            if c.strip()}
    assert JOB_CLASS_METHODS <= caps, JOB_CLASS_METHODS - caps
    # Documented as interactive on purpose (§2A.7: "Viz straddles ... don't
    # pre-design"), so their presence here is a decision, not an oversight.
    for viz in ("render_viz_doc", "viz_preview", "validate_generated_visualization"):
        assert viz in caps and not is_job_class(viz)

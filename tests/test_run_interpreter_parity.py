"""Plan §D / API-survey seam #2 — runs and env workers pick interpreters by
one rule, not two.

`composite_subprocess` spawned with a bare `sys.executable` while env workers
went through `resolve_interpreter`, so one workspace could be served by two
different environments.

The obvious repair — defer to the env worker's rule — is wrong, and these pin
why: a run child imports `vivarium_workbench` itself, and a workspace venv
provisions the WORKSPACE's dependencies and generally does not carry the
workbench. Switching wholesale trades one broken case for another.
"""
from __future__ import annotations

import subprocess
import sys

from vivarium_workbench.lib import env_resolver


def _venv(tmp_path, name=".venv"):
    """A workspace with a plausible-looking venv interpreter."""
    d = tmp_path / name / "bin"
    d.mkdir(parents=True)
    py = d / "python"
    py.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o755)
    return py


def test_a_workspace_venv_that_can_import_the_workbench_is_used(tmp_path, monkeypatch):
    """The point of the change: the child gets the workspace's real dependency
    tree instead of the server's."""
    py = _venv(tmp_path)
    monkeypatch.setattr(env_resolver, "resolve_interpreter", lambda ws: str(py))
    monkeypatch.setattr(env_resolver, "_run_capable", {})
    monkeypatch.setattr(
        env_resolver.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 0),
    )
    assert env_resolver.resolve_run_interpreter(tmp_path) == str(py)


def test_a_venv_without_the_workbench_falls_back_rather_than_failing_in_the_child(
    tmp_path, monkeypatch, caplog
):
    """THE case that makes a naive swap wrong. A workspace venv carrying the
    science stack but not the workbench must not be handed a child that does
    `from vivarium_workbench.lib import emitters`."""
    py = _venv(tmp_path)
    monkeypatch.setattr(env_resolver, "resolve_interpreter", lambda ws: str(py))
    monkeypatch.setattr(env_resolver, "_run_capable", {})
    monkeypatch.setattr(env_resolver, "_warned_run_fallback", set())
    monkeypatch.setattr(
        env_resolver.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 1),
    )
    with caplog.at_level("WARNING"):
        got = env_resolver.resolve_run_interpreter(tmp_path)
    assert got == sys.executable
    assert "cannot import" in caplog.text
    assert str(py) in caplog.text          # names WHICH interpreter was rejected


def test_the_probe_runs_once_per_interpreter_not_once_per_run(tmp_path, monkeypatch):
    """A run is minutes long, but a campaign is many runs; the probe is a real
    subprocess and must not be paid repeatedly."""
    py = _venv(tmp_path)
    calls: list = []
    monkeypatch.setattr(env_resolver, "resolve_interpreter", lambda ws: str(py))
    monkeypatch.setattr(env_resolver, "_run_capable", {})

    def _run(*a, **k):
        calls.append(a)
        return subprocess.CompletedProcess(a[0] if a else [], 0)

    monkeypatch.setattr(env_resolver.subprocess, "run", _run)
    for _ in range(5):
        env_resolver.resolve_run_interpreter(tmp_path)
    assert len(calls) == 1, calls


def test_when_resolution_already_lands_on_this_interpreter_no_probe_is_spent(
    tmp_path, monkeypatch
):
    """The common local case: nothing to verify, because it is us."""
    calls: list = []
    monkeypatch.setattr(env_resolver, "resolve_interpreter", lambda ws: sys.executable)
    monkeypatch.setattr(env_resolver, "_run_capable", {})
    monkeypatch.setattr(
        env_resolver.subprocess, "run", lambda *a, **k: calls.append(a) or None
    )
    assert env_resolver.resolve_run_interpreter(tmp_path) == sys.executable
    assert calls == []


def test_a_broken_interpreter_falls_back_instead_of_raising(tmp_path, monkeypatch):
    """A resolved path that cannot even be executed must not take the run with
    it — the fallback is the whole safety property here."""
    monkeypatch.setattr(env_resolver, "resolve_interpreter", lambda ws: "/nope/python")
    monkeypatch.setattr(env_resolver, "_run_capable", {})
    monkeypatch.setattr(env_resolver, "_warned_run_fallback", set())

    def _boom(*a, **k):
        raise OSError("no such file")

    monkeypatch.setattr(env_resolver.subprocess, "run", _boom)
    assert env_resolver.resolve_run_interpreter(tmp_path) == sys.executable


def test_composite_subprocess_asks_the_resolver_rather_than_using_sys_executable():
    """Source-level, because the alternative is spawning a real run: the seam
    this fix exists to close is the literal `py = sys.executable`."""
    import pathlib

    src = pathlib.Path(env_resolver.__file__).parent.joinpath("composite_subprocess.py").read_text()
    assert "py = sys.executable" not in src
    assert "resolve_run_interpreter" in src

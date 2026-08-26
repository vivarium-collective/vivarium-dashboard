"""EnvironmentResolver interpreter selection (in-place local adapter)."""
import sys
from pathlib import Path

import pytest

from vivarium_workbench.lib import env_resolver


def test_falls_back_to_running_interpreter_without_venv(tmp_path):
    assert env_resolver.resolve_interpreter(tmp_path) == sys.executable


def test_uses_the_workspace_venv_when_present(tmp_path):
    venv_py = tmp_path / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/bin/sh\n")   # just needs to be a file
    assert env_resolver.resolve_interpreter(tmp_path) == str(venv_py)


def test_worktree_borrows_the_main_checkouts_venv(tmp_path):
    # Main checkout with a provisioned venv.
    main = tmp_path / "repo"
    main_py = main / ".venv" / "bin" / "python"
    main_py.parent.mkdir(parents=True)
    main_py.write_text("#!/bin/sh\n")
    # A linked worktree with NO venv of its own; its `.git` is a gitdir file.
    wt = tmp_path / "repo--task"
    wt.mkdir()
    (wt / ".git").write_text(
        "gitdir: %s/.git/worktrees/repo--task\n" % main
    )
    assert env_resolver.resolve_interpreter(wt) == str(main_py)


def test_worktree_without_main_venv_falls_back(tmp_path):
    main = tmp_path / "repo"
    main.mkdir()
    wt = tmp_path / "repo--task"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: %s/.git/worktrees/repo--task\n" % main)
    assert env_resolver.resolve_interpreter(wt) == sys.executable


# ---------------------------------------------------------------------------
# base-workspace venv fallback (#936)
# ---------------------------------------------------------------------------

class TestBaseWorkspaceVenvFallback:
    """A materialized build has no venv of its own; it borrows the base one.

    `materialize_build` extracts a tarball and never provisions an environment,
    so every workspace under `build-cache/` hits this path. Before 0.3.56 they
    silently used `sys.executable` (the fat image's science venv); the slim
    image plus the strict guard turned that into a hard failure.
    """

    def _venv(self, root: Path) -> Path:
        p = root / ".venv" / "bin" / "python"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("#!/bin/sh\n")
        p.chmod(0o755)
        return p

    def test_build_without_venv_borrows_the_base(self, tmp_path, monkeypatch):
        base = tmp_path / "workspace"
        base.mkdir()
        interp = self._venv(base)
        build = base / "build-cache" / "sim82-234dc76"
        build.mkdir(parents=True)

        monkeypatch.setenv("VIVARIUM_WORKBENCH_WORKSPACE", str(base))
        monkeypatch.setenv("VIVARIUM_WORKBENCH_REQUIRE_WORKSPACE_VENV", "1")
        from vivarium_workbench.lib.env_resolver import resolve_interpreter
        assert resolve_interpreter(build) == str(interp)

    def test_a_workspace_with_its_own_venv_still_wins(self, tmp_path, monkeypatch):
        base = tmp_path / "workspace"
        base.mkdir()
        self._venv(base)
        build = base / "build-cache" / "sim99"
        build.mkdir(parents=True)
        own = self._venv(build)

        monkeypatch.setenv("VIVARIUM_WORKBENCH_WORKSPACE", str(base))
        from vivarium_workbench.lib.env_resolver import resolve_interpreter
        assert resolve_interpreter(build) == str(own)

    def test_strict_still_raises_when_there_is_nothing_to_borrow(self, tmp_path, monkeypatch):
        """The guard must not be defeated: no base venv means no silent fallback."""
        base = tmp_path / "workspace"
        (base / "build-cache").mkdir(parents=True)
        build = base / "build-cache" / "sim1"
        build.mkdir()

        monkeypatch.setenv("VIVARIUM_WORKBENCH_WORKSPACE", str(base))
        monkeypatch.setenv("VIVARIUM_WORKBENCH_REQUIRE_WORKSPACE_VENV", "1")
        from vivarium_workbench.lib.env_resolver import resolve_interpreter
        from vivarium_workbench.lib.env_worker_client import EnvWorkerUnavailable
        with pytest.raises(EnvWorkerUnavailable):
            resolve_interpreter(build)

    def test_the_base_itself_does_not_borrow_from_itself(self, tmp_path, monkeypatch):
        """No self-reference: a base with no venv must fail, not loop."""
        base = tmp_path / "workspace"
        base.mkdir()
        monkeypatch.setenv("VIVARIUM_WORKBENCH_WORKSPACE", str(base))
        monkeypatch.setenv("VIVARIUM_WORKBENCH_REQUIRE_WORKSPACE_VENV", "1")
        from vivarium_workbench.lib.env_resolver import resolve_interpreter
        from vivarium_workbench.lib.env_worker_client import EnvWorkerUnavailable
        with pytest.raises(EnvWorkerUnavailable):
            resolve_interpreter(base)

    def test_no_base_configured_falls_through_as_before(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VIVARIUM_WORKBENCH_WORKSPACE", raising=False)
        monkeypatch.delenv("VIVARIUM_WORKBENCH_REQUIRE_WORKSPACE_VENV", raising=False)
        import sys
        from vivarium_workbench.lib.env_resolver import resolve_interpreter
        assert resolve_interpreter(tmp_path) == sys.executable

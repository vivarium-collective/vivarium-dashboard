"""EnvironmentResolver interpreter selection (in-place local adapter)."""
import sys

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

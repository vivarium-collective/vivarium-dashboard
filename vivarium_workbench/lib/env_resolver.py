"""`EnvironmentResolver` — resolve a workspace to a runnable interpreter.

The seam that decides *which Python* a workspace's env worker runs on. See
`docs/materialization-lifecycle.md` §2a/§2b and `docs/workspace-store.md` §8.

**Slice scope — the in-place local adapter only.** If the workspace checkout has
its own venv (`<ws>/.venv`, the default `uv sync` layout, materialization §2a),
use *its* interpreter — so a v2ecoli workspace builds under its provisioned
3.12.12 (§2b) regardless of what Python the workbench runs. Otherwise fall back to
the running interpreter, which is today's shared-env behavior — **behavior-
preserving for a workspace without a venv** (the fixtures, the demo image where
v2ecoli is co-installed). The *managed* path (materialize a venv via clone +
`uv sync`, keyed by the environment coordinate) arrives with the materialization
lifecycle; this resolver is where that adapter plugs in.
"""
from __future__ import annotations

import sys
from pathlib import Path

# venv interpreter relative paths — POSIX first (macOS/Linux, day one), then the
# Windows layout (materialization-lifecycle §2b: Windows is a later target).
_VENV_INTERPRETERS = (".venv/bin/python", ".venv/Scripts/python.exe")


def _linked_worktree_main(ws: Path) -> Path | None:
    """If ``ws`` is a linked git worktree, return its MAIN checkout root.

    A linked worktree's ``.git`` is a file ``gitdir: <main>/.git/worktrees/<name>``.
    The main checkout (where ``uv sync`` provisioned ``.venv``) is the path just
    above that ``.git`` — so a worktree with no venv of its own can borrow it.
    """
    dotgit = ws / ".git"
    try:
        if not dotgit.is_file():
            return None
        text = dotgit.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir:"):
            return None
        gitdir = Path(text.split(":", 1)[1].strip())
        parts = gitdir.parts
        if ".git" in parts:
            return Path(*parts[: parts.index(".git")])
    except Exception:
        return None
    return None


def resolve_interpreter(workspace: Path | str) -> str:
    """The interpreter the workspace's env worker should run on.

    In-place local adapter: the checkout's own `.venv` if present; else, for a
    git worktree, the MAIN checkout's `.venv` (worktrees share the provisioned
    environment); else the running interpreter (`sys.executable`).
    """
    ws = Path(workspace)
    for rel in _VENV_INTERPRETERS:
        cand = ws / rel
        if cand.is_file():
            return str(cand)
    # A linked worktree (e.g. `<repo>--<task>`) rarely has its own `.venv`; use
    # the main checkout's so it builds under the workspace's real dependencies
    # (e.g. viva_human_atlas needs pbg_biomodels, absent from the server's venv).
    main = _linked_worktree_main(ws)
    if main is not None:
        for rel in _VENV_INTERPRETERS:
            cand = main / rel
            if cand.is_file():
                return str(cand)
    # A managed venv provisioned for this workspace's environment coordinate
    # (materialization-lifecycle §5), if one exists. Behavior-preserving today —
    # nothing populates the store until the managed path runs `uv sync` — so a
    # workspace without a `.venv` still falls through to the running interpreter.
    from vivarium_workbench.lib import materialization
    managed = materialization.cached_interpreter_for(ws)
    if managed is not None:
        return managed
    return sys.executable

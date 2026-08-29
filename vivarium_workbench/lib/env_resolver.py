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

import logging
import subprocess
import sys
from pathlib import Path

from vivarium_workbench.lib.env_compat import get_env

_log = logging.getLogger(__name__)

#: Workspaces already warned about (one line per workspace, not per call).
_warned_no_venv: set[str] = set()

#: Workspaces already warned about borrowing the base venv.
_warned_borrowed: set[str] = set()

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
    return _fallback_interpreter(ws)


#: Interpreters already checked for `vivarium_workbench`, so the probe below
#: costs one subprocess per interpreter per process, not one per run.
_run_capable: dict[str, bool] = {}


def resolve_run_interpreter(workspace: Path | str) -> str:
    """The interpreter a RUN subprocess should use — which is not the same
    question :func:`resolve_interpreter` answers, and the difference is why the
    two paths had drifted.

    `composite_subprocess` spawned with a bare ``sys.executable`` while env
    workers went through ``resolve_interpreter``, so the same workspace could be
    served by two different environments (plan §D, and seam #2 of the API
    survey). The obvious repair — just call ``resolve_interpreter`` — is WRONG,
    and quietly so:

    * an **env worker** needs only the workspace's own stack, because its worker
      module is staged separately from the workbench image (that is what
      ``ENV_WORKER_MODULE_IMAGE`` is for, and why it must equal the workbench
      tag);
    * a **run child** additionally does ``from vivarium_workbench.lib import
      emitters / composite_runs / result_fingerprint / generation`` inside the
      generated script. A workspace ``.venv`` provisions the *workspace's*
      dependencies and generally does **not** carry the workbench itself, so
      switching wholesale would trade one broken case for another —
      ``ModuleNotFoundError: vivarium_workbench`` deep inside a child.

    So: prefer the resolved interpreter, but only if it can actually import the
    workbench; otherwise keep ``sys.executable`` and say why, once. That gets the
    workspace's real dependency tree wherever the venv is complete, keeps every
    existing local setup working, and removes the *silent* divergence.

    The check is a real import in a real subprocess because that is the only
    thing that answers it — a venv can exist, be on the right path, and still not
    have the package.
    """
    resolved = resolve_interpreter(workspace)
    if resolved == sys.executable:
        return resolved
    ok = _run_capable.get(resolved)
    if ok is None:
        try:
            ok = subprocess.run(
                [resolved, "-c", "import vivarium_workbench"],
                capture_output=True, timeout=60, check=False,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        _run_capable[resolved] = ok
    if ok:
        return resolved
    if resolved not in _warned_run_fallback:
        _warned_run_fallback.add(resolved)
        _log.warning(
            "run subprocess: %s resolves to %s, which cannot import "
            "vivarium_workbench; using this server's interpreter instead. The "
            "child needs BOTH the workspace's dependencies and the workbench, "
            "so a workspace venv without the workbench cannot serve a run.",
            workspace, resolved,
        )
    return sys.executable


_warned_run_fallback: set[str] = set()


def _base_workspace_interpreter(ws: Path) -> str | None:
    """The venv of the workspace this server was STARTED with, if it has one.

    A workspace materialized under ``build-cache/`` (a pinned remote run, a
    session build) has no venv of its own -- ``materialize_build`` extracts a
    tarball and never provisions an environment. Before 0.3.56 such a workspace
    fell through to ``sys.executable``, which in the old fat image WAS the full
    science environment, so switch-to-build silently borrowed it and worked.
    The slim image removed that, and the strict guard turned the silence into a
    hard failure (#936).

    Borrowing the BASE workspace's venv restores that behaviour deliberately
    rather than by accident: a build materialized from the same simulator shares
    its dependency tree, which is exactly what the baked venv used to provide.

    This is explicitly a bridge, not the destination. It reintroduces the
    property that a build pinned to an older commit runs under the base
    workspace's dependencies -- item 44's failure mode across workspaces. #937
    tracks the real fix: give every materialized workspace its own venv, which
    hardlinking makes nearly free.

    Deliberately NOT ``_root.get_workspace_root()``: that returns the *active*
    root, which is the switched-to workspace itself -- circular. This is the
    boot workspace (``--workspace`` / ``VIVARIUM_WORKBENCH_WORKSPACE``).
    """
    base = (get_env("WORKSPACE", "") or "").strip()
    if not base:
        return None
    base_path = Path(base)
    if base_path == ws:          # the base itself has no venv; nothing to borrow
        return None
    for rel in _VENV_INTERPRETERS:
        cand = base_path / rel
        if cand.is_file():
            return str(cand)
    return None


def _fallback_interpreter(ws: Path) -> str:
    """The running interpreter — with a guard for environments that can't serve.

    Falling back to ``sys.executable`` is correct wherever the running
    interpreter genuinely has the workspace's dependencies: the test fixtures,
    and local development from a venv that installed them.

    It is NOT correct in the slim server image (#932), which deliberately ships
    only the workbench and its own dependencies — no workspace package, no
    science stack. There, a silent fallback would run analysis code in an
    interpreter that cannot import what it needs, and fail deep inside a worker
    call with a confusing ModuleNotFoundError instead of at the seam that made
    the wrong choice.

    So the image sets ``VIVARIUM_WORKBENCH_REQUIRE_WORKSPACE_VENV=1`` and gets a
    loud, actionable failure; everywhere else keeps today's behavior plus a
    one-time warning naming the workspace.
    """
    borrowed = _base_workspace_interpreter(ws)
    if borrowed is not None:
        if str(ws) not in _warned_borrowed:
            _warned_borrowed.add(str(ws))
            _log.warning(
                "workspace %s has no .venv; borrowing the base workspace's "
                "interpreter (%s). Correct only while that workspace's "
                "dependencies match -- see issue #937.", ws, borrowed,
            )
        return borrowed

    strict = (get_env("REQUIRE_WORKSPACE_VENV", "") or "").strip().lower() \
        not in ("", "0", "false", "no")
    if strict:
        # EnvWorkerUnavailable (not a novel exception type) so existing callers
        # degrade the route as they already do for an unusable worker, rather
        # than 500ing on something they've never seen.
        from vivarium_workbench.lib.env_worker_client import EnvWorkerUnavailable
        raise EnvWorkerUnavailable(
            f"workspace has no .venv: {ws}\n"
            "This deployment requires each workspace to provide its own "
            "environment (VIVARIUM_WORKBENCH_REQUIRE_WORKSPACE_VENV is set). The "
            "server image ships only the workbench and its own dependencies, so "
            "falling back to it would run workspace code in an interpreter that "
            "cannot import the workspace package.\n"
            f"Provision one with: uv sync --project {ws}"
        )
    if str(ws) not in _warned_no_venv:
        _warned_no_venv.add(str(ws))
        _log.warning(
            "workspace %s has no .venv; env workers will run on the workbench's "
            "own interpreter (%s). That works only if it already has the "
            "workspace's dependencies.", ws, sys.executable,
        )
    return sys.executable

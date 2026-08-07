"""Served-version introspection for skill<->server skew detection.

Returns the short git revision of the *served tree* (this package's source
checkout) plus the installed package version. Dependency-light and side-effect
free so it is safe to expose in readonly mode: a failed/absent git only degrades
the ``git_rev`` field to ``"unknown"``, never raises.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _package_version() -> str:
    """Installed distribution version, else the in-tree ``__version__``, else
    ``"unknown"``. Never raises."""
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("vivarium-workbench")
    except Exception:  # noqa: BLE001 — best-effort
        pass
    try:
        from vivarium_workbench import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "unknown"


def _git_rev() -> str:
    """Short git SHA of the served tree (the directory this module lives in),
    or ``"unknown"`` when git is unavailable or the tree is not a repo."""
    here = Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:  # noqa: BLE001 — git missing / timeout / OS error
        return "unknown"
    if out.returncode != 0:
        return "unknown"
    rev = (out.stdout or "").strip()
    return rev or "unknown"


def server_version() -> dict[str, str]:
    """``{"git_rev": "<short sha>", "version": "<package version>"}``.

    Both fields degrade gracefully to ``"unknown"`` rather than failing.
    """
    return {"git_rev": _git_rev(), "version": _package_version()}

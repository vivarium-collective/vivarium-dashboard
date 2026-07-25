"""Hatchling build hook — build the vendored bigraph-loom bundle into the wheel.

`vivarium_workbench/loom/` is bigraph-loom's *source* (vendored in Task 8, which
dropped the `bigraph-loom @ git+...` dependency). The thing the server actually
serves is the Vite build output, `vivarium_workbench/loom/_dist`, resolved at
runtime by ``vivarium_workbench.loom_assets.asset_dir()``.

`_dist` is gitignored — a generated artifact, not source — so nothing in a clean
clone produces it. Before this hook, only the Docker image ran
`scripts/build_loom.sh`; every other install path (``pip install
vivarium-workbench``, ``uv pip install "vivarium-workbench @ git+https://..."``
— how workspaces consume this) built a wheel with the full TS source and **no
bundle**, and served a blank 404 Composite Explorer with no error to explain it.
The `artifacts` entry in pyproject packages `_dist` correctly when it exists;
the gap was purely that nothing built it.

This hook closes that gap by running the build as part of the wheel build.

Policy — the loom bundle is an OPTIONAL runtime asset, so a missing Node
toolchain never breaks the build:

- **default (wheel + editable)** — best-effort. If Node/npm is present the bundle
  is built and packaged; if not (or the build fails), warn and ship WITHOUT it.
  The server degrades gracefully (an "Explorer unavailable" state), so consumers
  that use the workbench as a library — the common case, installed in Node-less
  Docker/CI — are never blocked by a frontend asset they don't use. This is the
  fix for the ecosystem-wide "npm not found on PATH" `uv sync` failures.
- **publish path** — sets ``VIVARIUM_WORKBENCH_REQUIRE_LOOM=1`` to turn a missing
  bundle into a hard error, guaranteeing the read-only dashboard ships the
  Explorer. (GitHub runners have Node, so it's built there regardless; this is
  the belt-and-suspenders guard.)

An already-built `_dist` is reused (see ``_is_fresh``) so repeat builds and the
Docker image — which runs the script explicitly before installing — don't pay
for a redundant ``npm ci``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# Set to a non-empty value to skip the loom build entirely. Escape hatch for
# environments that supply _dist by other means (or genuinely don't need the
# Explorer, e.g. a docs build); deliberately explicit, never inferred.
SKIP_ENV = "VIVARIUM_WORKBENCH_SKIP_LOOM_BUILD"

# Set to a non-empty value to make a missing loom bundle a HARD ERROR. The
# DEFAULT is warn-and-ship-without: the workbench is consumed as a *library* by
# ~every pbg workspace, and those installs happen in Node-less environments
# (slim Docker images, CI without a JS toolchain). Hard-failing the wheel build
# there turns an optional frontend asset into a mandatory Node dependency for
# every downstream `uv sync` — which is exactly what broke builds ecosystem-wide.
# The dashboard *publish* path (which must ship the Explorer) sets this to 1.
REQUIRE_ENV = "VIVARIUM_WORKBENCH_REQUIRE_LOOM"


class LoomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        loom_dir = root / "vivarium_workbench" / "loom"
        dist_dir = loom_dir / "_dist"

        if os.environ.get(SKIP_ENV):
            self.app.display_waiting(
                f"{SKIP_ENV} set — skipping the loom bundle build")
            return

        # Nothing to build against (e.g. an sdist that excluded the source).
        if not (loom_dir / "package.json").is_file():
            self._missing(version, f"no loom source at {loom_dir}")
            return

        if self._is_fresh(loom_dir, dist_dir):
            self.app.display_info(f"loom bundle already built: {dist_dir}")
            return

        script = root / "scripts" / "build_loom.sh"
        if shutil.which("npm") is None:
            self._missing(version, "npm not found on PATH")
            return

        self.app.display_waiting("building the loom bundle (npm run build)…")
        try:
            subprocess.run(["bash", str(script)], cwd=str(root), check=True)
        except subprocess.CalledProcessError as exc:
            self._missing(version, f"{script.name} failed (exit {exc.returncode})")
            return

        if not (dist_dir / "index.html").is_file():
            self._missing(version, f"{script.name} ran but produced no {dist_dir}")

    @staticmethod
    def _is_fresh(loom_dir: Path, dist_dir: Path) -> bool:
        """True when `_dist` exists and no loom source file is newer than it.

        Deliberately coarse — an mtime comparison, not a content hash. Getting
        this wrong in the "stale" direction costs a rebuild; getting it wrong in
        the "fresh" direction would ship an out-of-date bundle, so anything
        ambiguous (missing entry point, unreadable mtime) counts as stale.
        """
        entry = dist_dir / "index.html"
        if not entry.is_file():
            return False
        try:
            built_at = entry.stat().st_mtime
            src = loom_dir / "src"
            candidates = list(src.rglob("*")) if src.is_dir() else []
            candidates += [loom_dir / "package.json", loom_dir / "vite.config.ts"]
            return all(p.stat().st_mtime <= built_at
                       for p in candidates if p.is_file())
        except OSError:
            return False

    def _missing(self, version: str, reason: str) -> None:
        """Warn and ship without the loom bundle by default; hard-fail only when
        the caller explicitly REQUIRES it (``VIVARIUM_WORKBENCH_REQUIRE_LOOM``).

        The bundle is an OPTIONAL runtime asset — the server degrades to a
        graceful "Explorer unavailable" when ``_dist`` is absent, it does not
        crash. So a missing Node toolchain (Docker / CI without JS) must not
        break the wheel build for the many consumers that use the workbench as a
        library and never open the Explorer. The publish path that must ship the
        Explorer opts into a hard error with ``REQUIRE_ENV=1``."""
        msg = (
            f"loom bundle not built — {reason}.\n"
            f"The Composite Explorer is served from vivarium_workbench/loom/_dist, "
            f"which is generated (gitignored), not source.\n"
            f"Install Node 20+ and build it with scripts/build_loom.sh to include it."
        )
        if os.environ.get(REQUIRE_ENV):
            raise RuntimeError(f"{msg}\n({REQUIRE_ENV} is set — treating as fatal.)")
        self.app.display_warning(
            f"warning: {msg}\n"
            f"Shipping without the Composite Explorer (the rest of the workbench "
            f"works normally). Set {REQUIRE_ENV}=1 to make this a hard error.")


# Hatchling discovers the hook class by scanning this module; the explicit
# alias keeps the entry point stable if the class is ever renamed.
hatch_build_hook = LoomBuildHook


def get_build_hook():  # pragma: no cover - hatchling calls the class directly
    return LoomBuildHook


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    print("this module is a hatchling build hook; run a build instead",
          file=sys.stderr)

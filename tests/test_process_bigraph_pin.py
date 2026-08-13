"""Static sanity check on the Dockerfile's process-bigraph/bigraph-schema
version-floor patch — catches config drift no other test would (nothing else
parses the Dockerfile).

Backlog item 44: the workbench pod went CrashLoopBackOff in production —
`ModuleNotFoundError: No module named 'process_bigraph.artifacts'` — because
the Dockerfile's `COPY --from=workspace` (Fix B, item 39) copies sms-ecoli's
own pre-built venv wholesale, then overlays vivarium-workbench via
`uv pip install --no-deps .`, which never enforces vivarium-workbench's own
declared floor (`process-bigraph>=1.8.2`, `bigraph-schema>=1.4.3`). Whatever
sms-ecoli happened to lock (confirmed live, via kubectl exec on the crashing
pod: `process-bigraph==1.5.0`, missing the `artifacts` submodule added a
month later upstream) is what actually ships, regardless of what
vivarium-workbench's own uv.lock says a from-scratch resolution would want.
bigraph-schema needs the identical treatment even though no direct
ImportError ever surfaced: process-bigraph 1.8.2's own pyproject.toml
requires bigraph-schema>=1.4.5 (stricter than vivarium-workbench's own
floor), and 1.4.5 fixed a real, dated bug in exactly the resolve/default path
Composite construction calls directly — sms-ecoli's locked 1.4.2 predates it.

The fix: an explicit, pinned `uv pip install --no-deps` step right after the
workspace copy, patching just these two packages to the EXACT commits
vivarium-workbench's own uv.lock already resolved — not a bare `--no-deps .`
re-resolve of the full tree (that would risk upgrading OTHER shared
substrate packages sms-ecoli's own code wasn't tested against; see memory
workbench-image-process-bigraph-version-floor-risk for why `--no-deps` exists
at all here). These tests assert the Dockerfile's hardcoded pins stay in sync
with uv.lock, so future drift (someone bumps a version in pyproject.toml
without updating the Dockerfile) is caught by CI, not rediscovered as a live
incident.
"""

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
UV_LOCK = REPO_ROOT / "uv.lock"

PINNED_PACKAGES = ("process-bigraph", "bigraph-schema")


def _non_comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.strip().startswith("#")]


def _locked_git_commit(lock: dict, package_name: str) -> str:
    matches = [pkg for pkg in lock["package"] if pkg["name"] == package_name]
    assert len(matches) == 1, (
        f"expected exactly one uv.lock entry for {package_name!r}, found {len(matches)}"
    )
    source = matches[0].get("source", {})
    git_url = source.get("git", "")
    assert "#" in git_url, (
        f"expected {package_name!r}'s uv.lock source to be a git URL with a "
        f"pinned commit fragment ('...#<sha>'), got: {git_url!r}"
    )
    return git_url.rsplit("#", maxsplit=1)[-1]


def test_dockerfile_patches_both_version_floor_packages() -> None:
    """Both process-bigraph and bigraph-schema must be explicitly re-installed
    after the workspace copy — bumping only one and leaving the other to
    `--no-deps` inheritance reproduces the exact gap item 44 found (a package
    version below what the OTHER just-bumped package itself requires)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    missing = [name for name in PINNED_PACKAGES if name not in text]
    assert not missing, (
        f"Dockerfile must explicitly patch every version-floor package: missing {missing}"
    )


def test_dockerfile_pins_match_workbenchs_own_uv_lock() -> None:
    """The Dockerfile's hardcoded git-commit pins must match the exact commits
    vivarium-workbench's own uv.lock already resolved -- not a looser floor,
    not a different commit. If uv.lock moves (a real dependency bump), this
    Dockerfile step must move with it in the same PR."""
    dockerfile_text = DOCKERFILE.read_text(encoding="utf-8")
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))

    mismatched = []
    for name in PINNED_PACKAGES:
        expected_commit = _locked_git_commit(lock, name)
        if expected_commit not in dockerfile_text:
            mismatched.append((name, expected_commit))

    assert not mismatched, (
        f"Dockerfile's pinned commit(s) don't match uv.lock's current resolution "
        f"-- update the Dockerfile's RUN line to match: {mismatched}"
    )


def test_dockerfile_version_floor_patch_uses_no_deps() -> None:
    """The patch install must stay `--no-deps` -- the whole point is touching
    ONLY these two packages, not re-resolving vivarium-workbench's full
    dependency tree against packages sms-ecoli's own code wasn't tested
    against (see the module docstring)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    patch_lines = [
        line for line in _non_comment_lines(text)
        if "process-bigraph @ git+" in line or "bigraph-schema @ git+" in line
    ]
    assert patch_lines, "expected to find the process-bigraph/bigraph-schema install line(s)"

    # The pins may be split across a multi-line `uv pip install ... \` block;
    # check the whole RUN instruction they belong to, not just the matched
    # lines themselves.
    run_blocks = re.split(r"\nRUN ", text)
    owning_block = next(
        (block for block in run_blocks if "process-bigraph @ git+" in block), None
    )
    assert owning_block is not None
    assert "--no-deps" in owning_block, (
        "the process-bigraph/bigraph-schema patch install must use --no-deps"
    )


def test_dockerfile_sanity_check_imports_api_app() -> None:
    """The build-time sanity check must import vivarium_workbench.api.app
    explicitly -- item 44's actual crash was in THIS import chain, but a bare
    `import vivarium_workbench` doesn't eagerly pull in `api.app`, so the
    prior sanity check shipped straight past this exact regression and it
    only surfaced as a live CrashLoopBackOff. Without this, a future version-
    floor regression would again pass the build and fail only in prod."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    sanity_lines = [
        line for line in _non_comment_lines(text)
        if "import vivarium_workbench.api.app" in line
    ]
    assert sanity_lines, (
        "expected the build-time sanity check to 'import vivarium_workbench.api.app' "
        "-- the actual chain that crashed in item 44"
    )

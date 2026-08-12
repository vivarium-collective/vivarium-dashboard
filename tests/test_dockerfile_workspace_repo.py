"""Static sanity check on how the Dockerfile acquires its workspace
environment — catches config drift no other test would (nothing else parses
the Dockerfile).

See the Dockerfile's own comment on this ARG for the incident this guards:
the workbench's Docker image used to `git clone` a workspace repo at build
time (first hardcoded to vivarium-collective/v2ecoli, later a parameterized
but still-hardcoded-default WORKSPACE_REPO_URL) to resolve
v2ecoli.workflow.analysis.ANALYSIS_REGISTRY for remote-dispatch analysis-name
translation (lib/study_run_post.py's build_analysis_options()) —
disconnected from whichever commit is actually being dispatched, AND (once
sms-ecoli went private) unbuildable in CI at all, since GitHub Actions has no
credential for the private clone. Fix B replaces the git-clone with a
multi-stage COPY from sms-ecoli's own already-published, per-commit ECR
image — pulling a container image is a standard, already-solved auth
pattern; git-cloning an arbitrary private repo is not. (Fix A, the actual
runtime bug — build_analysis_options resolving against a build-time-baked
venv instead of the live served workspace — lives entirely in application
code; see tests/test_study_run_post_lib.py.)
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"


def _non_comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.strip().startswith("#")]


def test_dockerfile_does_not_git_clone_a_workspace_repo() -> None:
    """No build-time git clone of /app/v2ecoli — that was the whole bug."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    clone_lines = [
        line for line in _non_comment_lines(text)
        if "git clone" in line and "v2ecoli" in line
    ]
    assert not clone_lines, (
        f"Dockerfile must not git-clone a workspace repo at build time: {clone_lines}"
    )


def test_dockerfile_has_no_hardcoded_workspace_repo_url() -> None:
    """Neither the old wrong repo nor the canonical one may appear as a literal
    URL in an active instruction — the workspace comes from a pinned image
    (WORKSPACE_IMAGE), never a repo URL, so neither should ever reappear as a
    hardcoded clone target."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    code_lines = [
        line for line in _non_comment_lines(text)
        if "vivarium-collective/v2ecoli" in line or "CovertLabEcoli/sms-ecoli" in line
    ]
    assert not code_lines, (
        f"Dockerfile must not hardcode a workspace repo URL in any active "
        f"instruction (comments citing them as history are fine): {code_lines}"
    )


def test_dockerfile_workspace_image_arg_has_no_default() -> None:
    """WORKSPACE_IMAGE must be required, not defaulted — this ecosystem
    publishes per-commit tags only (no floating :main/:latest), so any
    guessed default would silently go stale exactly like the two hardcoded
    repo URLs before it. Every build must pass an explicit value."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^ARG WORKSPACE_IMAGE\s*$", text, re.MULTILINE), (
        "expected a bare 'ARG WORKSPACE_IMAGE' with no default"
    )
    assert not re.search(r"^ARG WORKSPACE_IMAGE=", text, re.MULTILINE), (
        "WORKSPACE_IMAGE must not have a default value"
    )


def test_dockerfile_has_a_named_workspace_stage_pulling_the_pinned_image() -> None:
    """A dedicated, named build stage pulls WORKSPACE_IMAGE — this is what
    later COPY --from=workspace instructions pull the workspace env from."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^FROM \$\{WORKSPACE_IMAGE\} AS workspace\s*$", text, re.MULTILINE), (
        "expected 'FROM ${WORKSPACE_IMAGE} AS workspace' declaring the pinned-image stage"
    )


def test_dockerfile_copies_v2ecoli_from_the_workspace_stage() -> None:
    """The main stage must COPY --from=workspace, never rebuild the env itself
    (no 'uv sync'/'uv python install' against a freshly-cloned source tree)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    copy_lines = [
        line for line in _non_comment_lines(text)
        if line.strip().startswith("COPY --from=workspace")
    ]
    assert copy_lines, "expected at least one 'COPY --from=workspace ...' instruction"
    assert any("/app/v2ecoli" in line for line in copy_lines), (
        f"expected a COPY --from=workspace of /app/v2ecoli, found: {copy_lines}"
    )


def test_dockerfile_sanity_check_imports_the_real_workspace_package_name() -> None:
    """The build-time sanity check must import the workspace's REAL top-level
    package name. Found 2026-08-12, the first time this Dockerfile ever built
    far enough to reach this step (every prior attempt failed earlier, at the
    git-clone-auth step): it still imported `pbg_v2ecoli`, a name that predates
    sms-ecoli replacing vivarium-collective/v2ecoli as the canonical workspace
    -- sms-ecoli's own pyproject.toml declares `name = "v2ecoli"` (bare, no
    `pbg_` prefix), matching what Fix A's build_analysis_options() already
    imports successfully in production (`from v2ecoli.workflow.analysis import
    ANALYSIS_REGISTRY`). sms-ecoli's own pbg_v2ecoli/ directory is dead (empty
    but for a stale __pycache__, zero .py source) -- importing it can only
    ever fail."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "import pbg_v2ecoli" not in text, (
        "Dockerfile must not import the stale 'pbg_v2ecoli' name -- "
        "sms-ecoli's real, current package is bare 'v2ecoli'"
    )
    sanity_lines = [
        line for line in _non_comment_lines(text)
        if "import v2ecoli" in line or "import pbg_v2ecoli" in line
    ]
    assert sanity_lines and any("import v2ecoli" in line for line in sanity_lines), (
        f"expected the build-time sanity check to 'import v2ecoli', found: {sanity_lines}"
    )

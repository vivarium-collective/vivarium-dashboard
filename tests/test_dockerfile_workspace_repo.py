"""Static sanity check on the Dockerfile's build-time workspace clone — catches
config drift no other test would (nothing else parses the Dockerfile).

See the Dockerfile's own comment on this ARG for the incident this guards:
the workbench's Docker image used to hardcode a clone of
vivarium-collective/v2ecoli (a structurally-diverged sibling repo) at build
time to resolve v2ecoli.workflow.analysis.ANALYSIS_REGISTRY for
remote-dispatch analysis-name translation (lib/study_run_post.py's
build_analysis_options()) — completely disconnected from whatever commit is
actually running. Every real deployment (incl. production, smscdk) silently
dropped any analysis name beyond that stale repo's much smaller registry,
with no error surfaced anywhere. Fixed by making the clone target a build ARG
(reusing the existing V2ECOLI_REF pattern) rather than hardcoding EITHER
repo — this image is shared across multiple deployments (smscdk,
smsvpctest), so the fix is a parameterized, overridable default, not a
different hardcoded value.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"

CANONICAL_WORKSPACE_REPO_URL = "https://github.com/CovertLabEcoli/sms-ecoli.git"


def test_dockerfile_clone_is_parameterized_not_hardcoded() -> None:
    """The clone command must use the ARG, never a literal repo URL — this
    image is shared by multiple deployments; a hardcoded value (either repo)
    forces every deployment onto the same workspace with no override."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    clone_lines = [line for line in text.splitlines() if "git clone" in line]
    workspace_clone_lines = [line for line in clone_lines if "/app/v2ecoli" in line]
    assert len(workspace_clone_lines) == 1, (
        f"expected exactly one clone of /app/v2ecoli, found {len(workspace_clone_lines)}"
    )
    assert "${WORKSPACE_REPO_URL}" in workspace_clone_lines[0], (
        "the workspace clone must reference the WORKSPACE_REPO_URL build ARG, "
        f"not a literal URL: {workspace_clone_lines[0]!r}"
    )
    # A prose comment mentioning the old wrong repo by name (as historical
    # explanation, like this file's own module docstring) is fine — only
    # non-comment lines (ARG defaults, RUN commands) must never hardcode it.
    code_lines = [
        line for line in text.splitlines()
        if not line.strip().startswith("#") and "vivarium-collective/v2ecoli" in line
    ]
    assert not code_lines, (
        f"Dockerfile must not hardcode vivarium-collective/v2ecoli in any active "
        f"instruction (comments mentioning it as history are fine): {code_lines}"
    )


def test_dockerfile_workspace_repo_default_is_sms_ecoli() -> None:
    """Both currently-live deployments (smscdk, smsvpctest) dispatch against
    sms-ecoli and pass no build-arg override — the DEFAULT must match what an
    unparameterized build actually needs to serve correctly."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"^ARG WORKSPACE_REPO_URL=(\S+)\s*$", text, re.MULTILINE)
    assert match is not None, "expected an ARG WORKSPACE_REPO_URL=<default> line"
    assert match.group(1) == CANONICAL_WORKSPACE_REPO_URL


def test_dockerfile_v2ecoli_ref_arg_still_present() -> None:
    """The clone target is now parameterized too; the pre-existing ref-selection
    ARG contract must still exist unchanged."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^ARG V2ECOLI_REF=", text, re.MULTILINE), (
        "V2ECOLI_REF build arg must still exist — kustomize/CI may pass it explicitly"
    )

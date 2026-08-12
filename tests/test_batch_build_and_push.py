"""Static sanity checks on deploy/batch-build-and-push.sh — catches config drift
no other test would (nothing else parses this script).

Backlog item 39: a local `deploy/build-and-push.sh` run on Apple Silicon builds
linux/amd64 under QEMU/Rosetta cross-arch emulation; v2ecoli's `polars` dependency
executes real AVX2/BMI2 instructions that emulation can't run, crashing the
Dockerfile's build-time sanity check with `Illegal instruction` (SIGILL) — an
environment gap, not a code bug. This script submits the same build to the
ALREADY-DEPLOYED AWS Batch DooD build path (sms-cdk's BuildBatchStack) that
already builds v2ecoli's own images on genuine amd64 EC2, instead of building
locally. See deploy/batch-build-and-push.sh's own header for the full story.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "deploy" / "batch-build-and-push.sh"


def _non_comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.strip().startswith("#")]


def test_batch_build_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"expected {SCRIPT} to exist"
    assert SCRIPT.stat().st_mode & 0o111, f"expected {SCRIPT} to be executable"


def test_batch_build_requires_workspace_image() -> None:
    """Same hard requirement as the local build script — no safe default exists
    for a per-commit-only ECR tag (see deploy/build-and-push.sh's own docstring)."""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        timeout=10,
    )
    assert result.returncode != 0
    assert "WORKSPACE_IMAGE is required" in result.stderr


def test_batch_build_derives_repo_url_from_git_remote_not_hardcoded() -> None:
    """This ecosystem has hit the hardcoded-repo-URL bug twice already (item 20,
    item 39's Dockerfile) — the Batch job's git-clone target must be resolved
    from `git remote get-url origin`, never a literal URL."""
    text = SCRIPT.read_text(encoding="utf-8")
    code_lines = [
        line for line in _non_comment_lines(text)
        if "vivarium-collective/vivarium-workbench" in line or "CovertLabEcoli" in line
    ]
    assert not code_lines, (
        f"script must not hardcode a repo URL in any active instruction: {code_lines}"
    )
    assert "remote get-url origin" in text


def test_batch_build_guards_ghcr_pat_from_xtrace() -> None:
    """The GHCR PAT fetch must be wrapped in set +x / set -x (matching viva-api's
    own SimulationServiceRay._build_command pattern) so the secret value never
    lands in CloudWatch logs via `set -ex` tracing."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set +x" in text
    assert "GHCR_PAT" in text
    fetch_idx = text.index("get-secret-value")
    guard_idx = text.rindex("set +x", 0, fetch_idx)
    unguard_idx = text.index("set -x", fetch_idx)
    assert guard_idx < fetch_idx < unguard_idx, (
        "expected 'set +x' before the secret fetch and 'set -x' after, "
        "so the PAT value is never traced into build logs"
    )


def test_batch_build_reuses_the_existing_build_and_push_script_unchanged() -> None:
    """Must not reimplement the docker buildx logic — reuse deploy/build-and-push.sh
    exactly as-is, inside the Batch job container."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "bash deploy/build-and-push.sh" in text
    buildx_lines = [line for line in _non_comment_lines(text) if "docker buildx build" in line]
    assert not buildx_lines, (
        f"the Batch script should delegate to build-and-push.sh, not duplicate its logic: {buildx_lines}"
    )


def test_batch_build_targets_the_live_batch_queue_and_job_definition() -> None:
    """Pins to the real, already-deployed queue/job-definition names (confirmed
    live via `aws batch describe-job-queues`/`describe-job-definitions` — see
    backlog item 39). A rename in sms-cdk without updating this script would
    submit to a queue that doesn't exist."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'QUEUE="smscdk-vecoli-build-amd64"' in text
    assert 'JOB_DEF="smscdk-vecoli-dind-build"' in text


def test_batch_build_confirms_target_commit_is_pushed_to_origin() -> None:
    """The Batch job clones origin fresh — it cannot see local uncommitted or
    unpushed work. A silent stale-commit build would be worse than a loud error."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "isn't on origin yet" in text
    assert "branch -r --contains" in text

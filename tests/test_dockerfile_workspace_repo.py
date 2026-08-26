"""Static sanity checks on how the Dockerfile acquires its environment.

Nothing else parses the Dockerfile, so config drift here is invisible to every
other test.

**History.** The image used to `git clone` a workspace repo at build time (first
a hardcoded vivarium-collective/v2ecoli, later a parameterized but
still-hardcoded-default WORKSPACE_REPO_URL) to resolve
`v2ecoli.workflow.analysis.ANALYSIS_REGISTRY` — disconnected from whichever
commit was actually being dispatched, and (once sms-ecoli went private)
unbuildable in CI at all, since GitHub Actions has no credential for the private
clone. Item 39 "Fix B" replaced the clone with a multi-stage COPY from
sms-ecoli's own published per-commit ECR image.

**Then #932 removed the COPY too.** Pulling that image required a GovCloud ECR
credential CI also never had, and the build-time `import v2ecoli` -> polars
needed AVX, which QEMU cannot emulate — so no Apple Silicon build could ever
succeed. The image now builds from this repo's own uv.lock and contains no
workspace package at all; the workspace supplies its environment at RUNTIME via
`<workspace>/.venv`, which is where EnvironmentResolver already sent every env
worker.

The five tests that asserted the WORKSPACE_IMAGE machinery (the arg, the
workspace stage, the COPY, the `import v2ecoli` sanity check, and the explicit
git-sourced-core-dep installs) are therefore gone — each asserted a mechanism
that no longer exists. The last of those deserves a note: it guarded a real
2026-08-12 ModuleNotFoundError where `viva-workspace` was missing because the
`--no-deps` install could not pull it from a foreign venv. `uv sync --frozen`
resolves every dependency from this repo's lock, so that failure mode is
structurally impossible rather than merely guarded.

The slim-image invariants that replaced them live in
tests/test_dockerfile_slim_image.py. What remains here is what still holds: the
build must not reach out to a workspace repo at all.
"""

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

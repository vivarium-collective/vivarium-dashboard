# syntax=docker/dockerfile:1
#
# vivarium-workbench DEMO image (combined). Approach A from docs/REFACTOR-PLAN.md
# §2B: the workbench must import the workspace's package (`v2ecoli`, via
# build_core) IN-PROCESS to render, so it needs the *same* environment v2ecoli
# runs in. Pulls that environment from the workspace's OWN published, per-commit
# image (WORKSPACE_IMAGE below — see backlog item 39, "Fix B") rather than
# git-cloning its source, then overlays THIS repo's workbench into that venv
# and serves.
#
# NOT baked (workbench renders; it does not run sims — those go to sms-api/Batch):
# the upstream vEcoli checkout + Cython, the AWS CLI, and the Ray-on-Batch
# entrypoint from v2ecoli's Dockerfile are intentionally omitted. Add V2E_VECOLI_DIR
# + the upstream checkout only if the demo renders an upstream-`vecoli` composite.
#
# Build (from this repo root):
#   docker build --build-arg WORKSPACE_IMAGE=<ecr-ref>:<commit-sha> \
#     -t ghcr.io/vivarium-collective/vivarium-workbench:dev .

# ─── workspace locked environment: COPIED from a published image, never
#     git-cloned (backlog item 39, Fix B) ─────────────────────────────────
#
# Historically this stage `git clone`d a workspace repo at build time (first
# vivarium-collective/v2ecoli hardcoded, later a parameterized
# WORKSPACE_REPO_URL ARG defaulting to CovertLabEcoli/sms-ecoli — see git
# history / tests/test_dockerfile_workspace_repo.py's own docstring for that
# incident). Both were the wrong LAYER: whichever repo got cloned into this
# build-time venv is what lib/study_run_post.py's build_analysis_options()
# used to import ANALYSIS_REGISTRY from — completely disconnected from
# whichever commit is actually being DISPATCHED at runtime, so any analysis
# name outside that stale build-time snapshot's registry got silently
# dropped with zero error surfaced anywhere. The real fix for THAT bug is in
# application code (build_analysis_options now takes ws_root and prepends
# the LIVE served workspace to sys.path before importing — see
# lib/study_run_post.py). Once that's fixed, this stage no longer needs to
# get the "right" repo at all for correctness — but it still needs A
# reasonably current, working sms-ecoli environment as the DEFAULT
# (unbound-session) serving target, and `git clone`-ing an arbitrary
# workspace repo at image-build time has a structural problem of its own:
# it requires this image's build environment to hold real git credentials
# for whatever repo is configured (this broke CI outright once sms-ecoli
# went private — GitHub Actions has no credential for it and none of this
# ecosystem's existing secret mechanisms bridge into GH Actions without
# inventing new OIDC infra from scratch).
#
# Fix B: stop git-cloning ANY workspace repo. sms-ecoli already publishes a
# real, versioned, per-commit image to ECR (docker/build-and-push-ecr.sh,
# 476270107793.dkr.ecr.us-gov-west-1.amazonaws.com/v2ecoli:<commit-sha> —
# the SAME image viva-api's own dispatch pulls for actual simulation jobs).
# Pulling a container image is a standard, already-solved auth pattern
# (`docker login`/`aws ecr get-login-password`) — a git-clone of an
# arbitrary private repo is not. WORKSPACE_IMAGE has NO default on purpose:
# this ecosystem deliberately publishes per-commit tags only, no floating
# `:main`/`:latest` (see sms-cdk/scripts/README.md) — a guessed default here
# would silently go stale exactly like the two hardcoded repo URLs before
# it. Every build must pass an explicit, intentional value. To resolve a
# current one: `atlantis simulator latest --repo-url
# https://github.com/CovertLabEcoli/sms-ecoli --branch main` (ensures a
# build for the current main tip exists, per this ecosystem's own canonical
# simulator-build protocol) and use the commit sha it reports.
ARG WORKSPACE_IMAGE
FROM ${WORKSPACE_IMAGE} AS workspace

FROM python:3.12-bookworm

# uv (pinned binary) for fast, lock-faithful installs — same as v2ecoli.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Build toolchain for v2ecoli's vendored Cython extensions + git for the git-main
# deps + Node/npm to build the vendored bigraph-loom bundle (Task 8; see the
# "vendored bigraph-loom" step below). git is also needed at RUNTIME (the live
# served /workspace is a real git working copy the app commits to).
#
# NodeSource's legacy `curl setup_20.x | bash -` piped installer was deprecated and
# now no-ops silently on some runners, leaving `apt-get install nodejs` to resolve
# Debian bookworm's nodejs — which ships WITHOUT npm (a separate package) → the loom
# build later died on `npm: command not found`. Use NodeSource's supported keyring +
# apt-repo method instead (stable, node 20 WITH npm), and assert node+npm exist at
# build time so a future regression fails loudly here, not 60 layers later.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git ca-certificates curl gnupg \
 && mkdir -p /etc/apt/keyrings \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update && apt-get install -y --no-install-recommends nodejs \
 && node --version && npm --version \
 && rm -rf /var/lib/apt/lists/*

# Self-contained venv (real wheel copies, not links into the BuildKit cache mount).
ENV UV_LINK_MODE=copy

# The published workspace image built its own locked venv (mirrors
# ../sms-ecoli/Dockerfile: `uv sync` under /app/v2ecoli, requires-python
# ==3.12.12 fetched via `uv python install`). Copy BOTH the project directory
# (source + .venv — an editable/local-package install can reference the
# source tree, not just site-packages) AND uv's managed-Python install dir
# (the venv's own `bin/python` resolves into
# /root/.local/share/uv/python/..., NOT a self-contained copy — omitting this
# would leave a dangling interpreter symlink). The build-time sanity check
# below fails loudly if either copy is incomplete, rather than shipping a
# silently broken interpreter.
COPY --from=workspace /app/v2ecoli /app/v2ecoli
COPY --from=workspace /root/.local/share/uv/python /root/.local/share/uv/python
WORKDIR /app/v2ecoli
ENV PATH="/app/v2ecoli/.venv/bin:${PATH}"

# ─── overlay THIS repo's workbench code ───────────────────────────────────────
# `--no-deps`: PyPI-published dependencies were already resolved by the sync
# above (avoiding a version-skew risk — see workbench-image-process-bigraph-
# version-floor-risk), so this only swaps the pinned git-main workbench for the
# exact code in this build context, and installs the `vivarium-workbench` /
# `vwb` console scripts into the venv.
WORKDIR /app/vivarium-workbench
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/v2ecoli/.venv/bin/python --no-deps .

# ─── vivarium-workbench's own non-PyPI, git-sourced core dependencies ─────────
# The workspace image's build EXCLUDES vivarium-workbench entirely (sms-ecoli's
# own Dockerfile: `uv sync --no-install-package vivarium-workbench`, since
# sms-ecoli doesn't need the workbench to run simulations) — so nothing unique
# to vivarium-workbench's own dependency tree ever lands in the pulled venv,
# on ANY build, regardless of how recently sms-ecoli was rebuilt (confirmed:
# WORKSPACE_IMAGE's pinned commit postdates viva-workspace's adoption below by
# days — this is a structural gap, not a staleness one). The `--no-deps`
# install above only swaps in this repo's own code; it can't pull these in.
# Found 2026-08-12: `viva-workspace` was the first of these to actually get
# exercised by a real build (every earlier build attempt failed even earlier,
# for unrelated reasons) — installing all 4 non-PyPI core deps here together,
# not just the one that happened to surface first, per pyproject.toml's own
# [tool.uv.sources] (the single source of truth for these refs — keep this
# list in sync with that section, not the other way around).
# `investigation-contracts` is pinned to a specific rev, NOT `main`, matching
# pyproject.toml's own deliberate choice there — a floating branch ref is
# exactly what hid a breaking pbg-superpowers change for ~3 weeks once already
# (issue #483); do not change this to `@main`.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/v2ecoli/.venv/bin/python --no-deps \
        "pbg-basic-processes @ git+https://github.com/vivarium-collective/pbg-basic-processes.git@main" \
        "viva-marketplace @ git+https://github.com/vivarium-collective/viva-marketplace.git@main" \
        "viva-workspace @ git+https://github.com/vivarium-collective/viva-workspace.git@main" \
        "investigation-contracts @ git+https://github.com/vivarium-collective/investigation-contracts.git@65c793fd231d952e49a9cfe4244797dadde1bedc"

# ─── overlay the Pathway Tools Omics-Viewer plugin (pbg-ptools) ───────────────
# The workbench discovers this at runtime via its pbg-* distribution scan and
# renders the PTools viewer (self-gated on ui.ptools_server_url). It MUST be
# installed explicitly: the `--no-deps` workbench install above does not pull the
# `ptools` extra, so without this line the viewer would be absent. `--no-deps`
# again because its deps (vivarium-workbench, pyyaml) are already in the venv.
ARG PBG_PTOOLS_REF=main
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/v2ecoli/.venv/bin/python --no-deps \
        "pbg-ptools @ git+https://github.com/vivarium-collective/pbg-ptools.git@${PBG_PTOOLS_REF}"

# ─── build the vendored bigraph-loom bundle (embedded state-tree explorer, served
#     at /loom-explore) ──────────────────────────────────────────────────────
# Task 8 vendored bigraph-loom's source into vivarium_workbench/loom/ and
# dropped the external `bigraph-loom @ git+...` dependency (it used to be
# installed as a separate package here because v2ecoli's lock never declared
# it). `_dist` (the Vite build output) is gitignored — a generated artifact —
# so it must be built now, from the source copied in by `COPY . .` above.
# `lib/static_serving.resolve_loom_asset()` / `publish.py` resolve it via
# `vivarium_workbench.loom_assets.asset_dir()`; a missing `_dist` would pass
# the build-time sanity import below and only 500 at runtime (the
# always-visible loom panel fires a loom-asset request for ANY composite).
RUN bash scripts/build_loom.sh

# Sanity: the workspace package, the workbench, the viewer plugin, and the loom
# explorer all import in one interpreter (the plugin's top-level imports exercise
# the workbench too). loom_assets is added here so a regression fails the BUILD
# rather than shipping a silent runtime ModuleNotFoundError (see the loom build
# above), and confirm the built bundle actually landed on disk.
RUN python -c "\
import v2ecoli, vivarium_workbench, pbg_ptools.workbench_viewers; \
from vivarium_workbench.loom_assets import asset_dir; \
d = asset_dir(); \
assert (d / 'index.html').is_file(), f'loom bundle missing: {d}'; \
print('combined env ok')"

# ─── serve ───────────────────────────────────────────────────────────────────
# The workspace (v2ecoli's workspace.yaml + studies/investigations/.git/runs.db)
# is mounted from the private EBS PVC at /workspace (see deploy/). SMS_API_BASE is
# set by the overlay to the in-cluster sms-api service. Bind 0.0.0.0 in-container.
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["vivarium-workbench"]
CMD ["serve", "--workspace", "/workspace", "--host", "0.0.0.0", "--port", "8000"]

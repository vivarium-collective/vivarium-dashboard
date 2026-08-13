#!/usr/bin/env bash
#
# Build + push the combined workbench image for the EKS cluster.
#
# The cluster nodes are x86_64, so this ALWAYS builds linux/amd64 (a native
# arm64 build from a Mac will not run there). Mirrors ../sms-api/kustomize/
# scripts/build_and_push.sh.
#
# Usage:
#   WORKSPACE_IMAGE=<ecr-ref>:<commit-sha> deploy/build-and-push.sh [version] [org]
#     version  image tag (default: short git sha)
#     org      ghcr org   (default: vivarium-collective)
#
# WORKSPACE_IMAGE (required): the sms-ecoli/v2ecoli image this build pulls its
# locked Python environment from (the Dockerfile's WORKSPACE_IMAGE build-arg —
# backlog item 39, "Fix B": the workbench no longer git-clones a workspace
# repo, it COPYs from this pinned, already-published image instead). This
# ecosystem publishes per-commit tags only (no floating :main/:latest — see
# sms-cdk/scripts/README.md), so there is no safe default to fall back to; a
# guessed one would silently go stale exactly like the two hardcoded repo
# URLs this replaced. To resolve a current value: `atlantis simulator latest
# --repo-url https://github.com/CovertLabEcoli/sms-ecoli --branch main`
# (ensures a build for the current main tip exists) and use the commit sha
# it reports, e.g.
# 476270107793.dkr.ecr.us-gov-west-1.amazonaws.com/v2ecoli:<sha>.
#
# Requires: docker buildx, a ghcr login (`docker login ghcr.io`) to push the
# result, AND an ECR login for whichever registry WORKSPACE_IMAGE lives in to
# pull it, e.g.:
#   aws ecr get-login-password --region us-gov-west-1 --profile stanford-sso \
#     | docker login --username AWS --password-stdin 476270107793.dkr.ecr.us-gov-west-1.amazonaws.com
set -euo pipefail

if [[ -z "${WORKSPACE_IMAGE:-}" ]]; then
  echo "error: WORKSPACE_IMAGE is required (see this script's header comment for how to resolve one)" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD)}"
ORG="${2:-vivarium-collective}"
IMAGE="ghcr.io/${ORG}/vivarium-workbench:${VERSION}"

# ${arr[@]+"${arr[@]}"} (not bare "${arr[@]}") so an empty BUILD_ARGS never
# trips `set -u`'s unbound-variable check on bash < 4.4 (this Mac's stock
# /bin/bash is 3.2.57) — BUILD_ARGS always has WORKSPACE_IMAGE today, but
# this guard is cheap insurance against the exact class of bug that once
# blocked a build here.
BUILD_ARGS=(--build-arg "WORKSPACE_IMAGE=${WORKSPACE_IMAGE}")

echo "building + pushing ${IMAGE} (linux/amd64, workspace image ${WORKSPACE_IMAGE})"
docker buildx build \
  --platform=linux/amd64 \
  -f "${ROOT_DIR}/Dockerfile" \
  -t "${IMAGE}" \
  "${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"}" \
  "${ROOT_DIR}" \
  --push

echo "pushed ${IMAGE}"
echo "pin it in deploy/kustomize/overlays/<env>/kustomization.yaml (images: newTag)"

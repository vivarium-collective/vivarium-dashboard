#!/usr/bin/env bash
#
# Build + push the combined workbench image for the EKS cluster.
#
# The cluster nodes are x86_64, so this ALWAYS builds linux/amd64 (a native
# arm64 build from a Mac will not run there). Mirrors ../sms-api/kustomize/
# scripts/build_and_push.sh.
#
# Usage:
#   deploy/build-and-push.sh [version] [org]
#     version  image tag (default: short git sha)
#     org      ghcr org   (default: vivarium-collective)
#
# WORKSPACE_REPO_URL env var, if set, is passed through as the Dockerfile's
# WORKSPACE_REPO_URL build-arg (which repo the image bakes an environment
# for) — unset means the Dockerfile's own default (CovertLabEcoli/sms-ecoli)
# applies. This image is shared across deployments that may serve different
# workspaces; set this when building for one that doesn't want the default.
#
# Requires: docker buildx + a ghcr login (`docker login ghcr.io`).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD)}"
ORG="${2:-vivarium-collective}"
IMAGE="ghcr.io/${ORG}/vivarium-workbench:${VERSION}"

BUILD_ARGS=()
if [[ -n "${WORKSPACE_REPO_URL:-}" ]]; then
  BUILD_ARGS+=(--build-arg "WORKSPACE_REPO_URL=${WORKSPACE_REPO_URL}")
fi

echo "building + pushing ${IMAGE} (linux/amd64)"
docker buildx build \
  --platform=linux/amd64 \
  -f "${ROOT_DIR}/Dockerfile" \
  -t "${IMAGE}" \
  "${BUILD_ARGS[@]}" \
  "${ROOT_DIR}" \
  --push

echo "pushed ${IMAGE}"
echo "pin it in deploy/kustomize/overlays/<env>/kustomization.yaml (images: newTag)"

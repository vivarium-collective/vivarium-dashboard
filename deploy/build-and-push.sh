#!/usr/bin/env bash
#
# Build + push the vivarium-workbench server image.
#
# The cluster nodes are x86_64, so this ALWAYS builds linux/amd64. Since #932
# the image contains only the workbench and its own locked dependencies -- no
# workspace package, no science stack -- so a cross-build from an ARM Mac works
# fine (~2 min, ~744 MB). It previously could not: the build imported v2ecoli ->
# polars, which needs AVX/AVX2/FMA/BMI, and QEMU does not emulate those, so
# every Apple Silicon build died with "Illegal instruction".
#
# Usage:
#   deploy/build-and-push.sh [version] [org]
#     version  image tag (default: short git sha)
#     org      ghcr org   (default: vivarium-collective)
#
# Optional:
#   PBG_PTOOLS_REF   git ref for the pbg-ptools Omics-Viewer plugin (default: main)
#
# Requires: docker buildx and a ghcr login (`docker login ghcr.io`) to push.
#
# NO LONGER REQUIRED (#932): WORKSPACE_IMAGE and an ECR login. The image no
# longer copies a venv out of a per-commit sms-ecoli/v2ecoli image, so nothing
# is pulled from GovCloud ECR. The workspace supplies the science environment at
# RUNTIME via <workspace>/.venv, which is where EnvironmentResolver already
# sends every env worker. If you have WORKSPACE_IMAGE exported from an older
# workflow, it is simply ignored.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD)}"
ORG="${2:-vivarium-collective}"
IMAGE="ghcr.io/${ORG}/vivarium-workbench:${VERSION}"

# ${arr[@]+"${arr[@]}"} (not bare "${arr[@]}") so an empty BUILD_ARGS never
# trips `set -u`'s unbound-variable check on bash < 4.4 (this Mac's stock
# /bin/bash is 3.2.57). Since #932 removed WORKSPACE_IMAGE, BUILD_ARGS really
# can be empty -- the guard stopped being theoretical.
BUILD_ARGS=()
if [[ -n "${PBG_PTOOLS_REF:-}" ]]; then
  BUILD_ARGS+=(--build-arg "PBG_PTOOLS_REF=${PBG_PTOOLS_REF}")
fi

echo "building + pushing ${IMAGE} (linux/amd64)"
docker buildx build \
  --platform=linux/amd64 \
  -f "${ROOT_DIR}/Dockerfile" \
  -t "${IMAGE}" \
  "${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"}" \
  "${ROOT_DIR}" \
  --push

echo "pushed ${IMAGE}"
echo "pin it in deploy/kustomize/overlays/<env>/kustomization.yaml (images: newTag)"

#!/usr/bin/env bash
#
# Build + push the combined workbench image via a real amd64 AWS Batch DooD job,
# instead of a local `docker buildx build`.
#
# Why this exists (backlog item 39): a local build on Apple Silicon builds
# linux/amd64 under QEMU/Rosetta cross-arch emulation. v2ecoli's `polars`
# dependency executes real AVX2/BMI2 x86 instructions that emulation can't
# correctly run, crashing the Dockerfile's own build-time sanity check with
# `Illegal instruction` (SIGILL) — an environment gap, not a code bug. This
# script extends the ALREADY-DEPLOYED, ALREADY-PROVEN AWS Batch build path
# (sms-cdk/lib/build-batch-stack.ts) that builds v2ecoli's own images on genuine
# amd64 EC2 (m7i/c7i, real AVX2) — same queue, same job definition, no new infra.
# Everything downstream still runs deploy/build-and-push.sh UNCHANGED, inside the
# Batch job container.
#
# Usage:
#   WORKSPACE_IMAGE=<ecr-ref>:<commit-sha> deploy/batch-build-and-push.sh [version] [org]
#     version  image tag (default: short git sha of the LOCAL checked-out commit)
#     org      ghcr org   (default: vivarium-collective)
#
# Requires:
#   - This repo's target commit already pushed to origin (the Batch job clones
#     origin fresh — it cannot see local uncommitted changes).
#   - The `vivarium-workbench-ghcr-pat` secret already created in Secrets Manager
#     (write:packages-scoped GitHub PAT — see backlog item 39).
#   - The `smscdk-build-batch` CDK stack deployed (grants the DooD execution role
#     read access to that secret; already done as of item 39's fix).
set -euo pipefail

if [[ -z "${WORKSPACE_IMAGE:-}" ]]; then
  echo "error: WORKSPACE_IMAGE is required (see deploy/build-and-push.sh's header for how to resolve one)" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD)}"
ORG="${2:-vivarium-collective}"
COMMIT="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
BRANCH="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD)"
REPO_URL="$(git -C "${ROOT_DIR}" remote get-url origin | sed -E 's#^git@github\.com:#https://github.com/#; s#\.git$##').git"
ECR_REGISTRY="${WORKSPACE_IMAGE%%/*}"

REGION="us-gov-west-1"
QUEUE="smscdk-vecoli-build-amd64"
JOB_DEF="smscdk-vecoli-dind-build"
GHCR_SECRET_ARN="arn:aws-us-gov:secretsmanager:${REGION}:476270107793:secret:vivarium-workbench-ghcr-pat"
GHCR_USER="AlexPatrie"
LOG_GROUP="/aws/batch/job"

# The Batch job clones origin fresh, not the local working tree — a local-only
# commit would silently build stale code with zero warning otherwise.
if ! git -C "${ROOT_DIR}" branch -r --contains "${COMMIT}" | grep -q "origin/${BRANCH}$"; then
  echo "error: ${COMMIT} (branch ${BRANCH}) isn't on origin yet — push it first" >&2
  exit 1
fi

BUILD_SCRIPT="$(cat <<SCRIPT
set -ex
apk add --no-cache aws-cli git bash

docker info >/dev/null 2>&1 || { echo "ERROR: Docker socket not available"; exit 1; }

git clone --branch ${BRANCH} --single-branch ${REPO_URL} /build/vivarium-workbench
cd /build/vivarium-workbench
git checkout ${COMMIT}

aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}

set +x
GHCR_PAT=\$(aws secretsmanager get-secret-value --secret-id ${GHCR_SECRET_ARN} --query SecretString --output text)
echo "\${GHCR_PAT}" | docker login ghcr.io --username ${GHCR_USER} --password-stdin
unset GHCR_PAT
set -x

WORKSPACE_IMAGE=${WORKSPACE_IMAGE} bash deploy/build-and-push.sh ${VERSION} ${ORG}
SCRIPT
)"

CONTAINER_OVERRIDES="$(jq -n --arg script "${BUILD_SCRIPT}" '{command: ["sh", "-c", $script]}')"

echo "submitting Batch build job (queue=${QUEUE}, commit=${COMMIT:0:12}, version=${VERSION})"
JOB_ID="$(aws batch submit-job \
  --region "${REGION}" \
  --job-name "vivarium-workbench-build-${VERSION}" \
  --job-queue "${QUEUE}" \
  --job-definition "${JOB_DEF}" \
  --container-overrides "${CONTAINER_OVERRIDES}" \
  --query jobId --output text)"

echo "job id: ${JOB_ID}"
echo "polling for terminal state (this can take 10+ minutes)..."

STATUS=""
while true; do
  STATUS="$(aws batch describe-jobs --region "${REGION}" --jobs "${JOB_ID}" --query 'jobs[0].status' --output text)"
  echo "  status: ${STATUS}"
  case "${STATUS}" in
    SUCCEEDED|FAILED) break ;;
  esac
  sleep 15
done

LOG_STREAM="$(aws batch describe-jobs --region "${REGION}" --jobs "${JOB_ID}" --query 'jobs[0].container.logStreamName' --output text)"

if [[ "${STATUS}" == "FAILED" ]]; then
  REASON="$(aws batch describe-jobs --region "${REGION}" --jobs "${JOB_ID}" --query 'jobs[0].statusReason' --output text)"
  echo "FAILED: ${REASON}" >&2
  echo "--- log stream: ${LOG_STREAM} ---" >&2
  aws logs get-log-events --region "${REGION}" --log-group-name "${LOG_GROUP}" \
    --log-stream-name "${LOG_STREAM}" --limit 200 --query 'events[].message' --output text >&2
  exit 1
fi

echo "pushed ghcr.io/${ORG}/vivarium-workbench:${VERSION}"
echo "pin it in viva-api/kustomize/overlays/<env>/kustomization.yaml (images: newTag)"

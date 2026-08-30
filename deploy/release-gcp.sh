#!/usr/bin/env bash
# Release pipeline for Terraform-managed environments.
# Builds immutable images (commit SHA tag), pushes to Artifact Registry,
# updates Cloud Run images only, waits for readiness, and rolls back on failure.
#
# Does NOT mutate IAM, secrets, CPU/memory, scaling, env vars, or service shape.
# Use infra/terraform apply for infrastructure; use this script for app releases.

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
AGENT_SERVICE="${GCP_AGENT_SERVICE:-teams-rag-agent}"
ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"

GIT_SHA="${RELEASE_GIT_SHA:-$(git -C "${PROJECT_DIR}" rev-parse --short HEAD)}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
AGENT_IMAGE="${REGISTRY}/${AGENT_SERVICE}:${GIT_SHA}"
ADAPTER_IMAGE="${REGISTRY}/${ADAPTER_SERVICE}:${GIT_SHA}"

log() {
  printf '[release] %s\n' "$*"
}

fail() {
  printf '[release] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

current_service_image() {
  local service="$1"
  gcloud run services describe "${service}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(spec.template.spec.containers[0].image)'
}

wait_for_cloud_run_ready() {
  local service="$1"
  local attempts="${2:-60}"
  local delay="${3:-5}"
  local i status
  for ((i = 1; i <= attempts; i++)); do
    status="$(gcloud run services describe "${service}" \
      --region="${REGION}" \
      --project="${PROJECT_ID}" \
      --format='value(status.conditions[?type=Ready].status)' 2>/dev/null || true)"
    if [[ "${status}" == "True" ]]; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

wait_for_adapter_readyz() {
  local adapter_url="$1"
  local attempts="${2:-30}"
  local delay="${3:-5}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl -sf "${adapter_url}/readyz" >/dev/null; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

rollback_service_image() {
  local service="$1"
  local previous_image="$2"
  [[ -n "${previous_image}" ]] || return 0
  log "Rolling back ${service} to ${previous_image}"
  gcloud run services update "${service}" \
    --image="${previous_image}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --quiet >/dev/null
  wait_for_cloud_run_ready "${service}" || true
}

require_cmd gcloud
require_cmd curl
require_cmd git
[[ -f "${PROJECT_DIR}/data/index/chunks.json" ]] || fail "Missing data/index/chunks.json — run uv run rag-index first"

PREVIOUS_AGENT_IMAGE="$(current_service_image "${AGENT_SERVICE}" || true)"
PREVIOUS_ADAPTER_IMAGE="$(current_service_image "${ADAPTER_SERVICE}" || true)"

rollback_all() {
  rollback_service_image "${AGENT_SERVICE}" "${PREVIOUS_AGENT_IMAGE}"
  rollback_service_image "${ADAPTER_SERVICE}" "${PREVIOUS_ADAPTER_IMAGE}"
}

trap 'status=$?; if [[ ${status} -ne 0 ]]; then log "Release failed — attempting rollback"; rollback_all; fi; exit ${status}' ERR

gcloud config set project "${PROJECT_ID}" >/dev/null

log "Building Agent image ${AGENT_IMAGE}"
gcloud builds submit "${PROJECT_DIR}" \
  --config="${PROJECT_DIR}/deploy/cloudbuild-agent.yaml" \
  --substitutions="_IMAGE=${AGENT_IMAGE}" \
  --project="${PROJECT_ID}"

log "Building Adapter image ${ADAPTER_IMAGE}"
gcloud builds submit "${PROJECT_DIR}" \
  --config="${PROJECT_DIR}/deploy/cloudbuild-adapter.yaml" \
  --substitutions="_IMAGE=${ADAPTER_IMAGE}" \
  --project="${PROJECT_ID}"

log "Updating Agent Cloud Run image only"
gcloud run services update "${AGENT_SERVICE}" \
  --image="${AGENT_IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null
wait_for_cloud_run_ready "${AGENT_SERVICE}" || fail "Agent service did not become Ready"

log "Updating Adapter Cloud Run image only"
gcloud run services update "${ADAPTER_SERVICE}" \
  --image="${ADAPTER_IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null
wait_for_cloud_run_ready "${ADAPTER_SERVICE}" || fail "Adapter service did not become Ready"

ADAPTER_URL="$(gcloud run services describe "${ADAPTER_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"
wait_for_adapter_readyz "${ADAPTER_URL}" || fail "Adapter /readyz did not succeed"

trap - ERR

printf '\nRelease complete.\n'
printf 'Git SHA:       %s\n' "${GIT_SHA}"
printf 'Agent image:   %s\n' "${AGENT_IMAGE}"
printf 'Adapter image: %s\n' "${ADAPTER_IMAGE}"
printf 'Adapter URL:   %s\n' "${ADAPTER_URL}"
printf 'Smoke:         curl -sS %s/readyz\n' "${ADAPTER_URL}"

#!/usr/bin/env bash
# Release pipeline for Terraform-managed environments.
# Builds immutable images (commit SHA tag), pushes to Artifact Registry,
# updates Cloud Run images only, waits for readiness, and rolls back on failure.
#
# Does NOT mutate IAM, secrets, CPU/memory, scaling, env vars, or service shape.
# Use infra/terraform apply for infrastructure; use this script for app releases.

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
AGENT_SERVICE="${GCP_AGENT_SERVICE:-teams-rag-agent}"
ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"
BACKOFFICE_SERVICE="${GCP_BACKOFFICE_SERVICE:-teams-ai-ops-backoffice}"
PORTAL_SERVICE="${GCP_PORTAL_SERVICE:-teams-knowledge-portal}"
CONVERTER_SERVICE="${GCP_PDF_CONVERTER_SERVICE:-teams-pdf-converter}"

CONSOLE_SERVICE="${GCP_CONSOLE_SERVICE:-}"
CONSOLE_IMAGE_NAME="${GCP_CONSOLE_IMAGE:-teams-ai-ops-console}"

GIT_SHA="${RELEASE_GIT_SHA:-$(git -C "${PROJECT_DIR}" rev-parse --short HEAD)}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
AGENT_IMAGE="${REGISTRY}/${AGENT_SERVICE}:${GIT_SHA}"
ADAPTER_IMAGE="${REGISTRY}/${ADAPTER_SERVICE}:${GIT_SHA}"
BACKOFFICE_IMAGE="${REGISTRY}/${BACKOFFICE_SERVICE}:${GIT_SHA}"
PORTAL_IMAGE="${REGISTRY}/${PORTAL_SERVICE}:${GIT_SHA}"
CONVERTER_IMAGE="${REGISTRY}/${CONVERTER_SERVICE}:${GIT_SHA}"
CONSOLE_IMAGE="${REGISTRY}/${CONSOLE_IMAGE_NAME}:${GIT_SHA}"
AGENT_CACHE_IMAGE="${REGISTRY}/${AGENT_SERVICE}:buildcache"
ADAPTER_CACHE_IMAGE="${REGISTRY}/${ADAPTER_SERVICE}:buildcache"
BACKOFFICE_CACHE_IMAGE="${REGISTRY}/${BACKOFFICE_SERVICE}:buildcache"
PORTAL_CACHE_IMAGE="${REGISTRY}/${PORTAL_SERVICE}:buildcache"
CONVERTER_CACHE_IMAGE="${REGISTRY}/${CONVERTER_SERVICE}:buildcache"

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
      --format='value(status.conditions[0].status)' 2>/dev/null || true)"
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

resolve_image_digest() {
  local image="$1"
  local digest
  digest="$(gcloud artifacts docker images describe "${image}" \
    --project="${PROJECT_ID}" \
    --format='value(image_summary.digest)')"
  [[ "${digest}" == sha256:* ]] || fail "Could not resolve digest for ${image}"
  printf '%s@%s\n' "${image%%:*}" "${digest}"
}

pin_image_reference() {
  local image="$1"
  if [[ "${image}" == *@sha256:* ]]; then
    printf '%s\n' "${image}"
    return
  fi
  resolve_image_digest "${image}"
}

select_components() {
  local requested="${RELEASE_COMPONENTS:-auto}"
  local changed_files base_ref
  BUILD_AGENT=0
  BUILD_ADAPTER=0
  BUILD_BACKOFFICE=0
  BUILD_PORTAL=0
  BUILD_CONVERTER=0
  BUILD_CONSOLE=0

  if [[ "${requested}" != "auto" ]]; then
    if [[ ",${requested}," == *",agent,"* ]]; then BUILD_AGENT=1; fi
    if [[ ",${requested}," == *",adapter,"* ]]; then BUILD_ADAPTER=1; fi
    if [[ ",${requested}," == *",backoffice,"* ]]; then BUILD_BACKOFFICE=1; fi
    if [[ ",${requested}," == *",portal,"* ]]; then BUILD_PORTAL=1; fi
    if [[ ",${requested}," == *",converter,"* ]]; then BUILD_CONVERTER=1; fi
    if [[ ",${requested}," == *",console,"* ]]; then BUILD_CONSOLE=1; fi
    return
  fi

  base_ref="${RELEASE_BASE_REF:-origin/main}"
  git -C "${PROJECT_DIR}" rev-parse --verify "${base_ref}" >/dev/null 2>&1 \
    || base_ref="HEAD^"
  changed_files="$(
    {
      git -C "${PROJECT_DIR}" diff --name-only "${base_ref}" -- || true
      git -C "${PROJECT_DIR}" ls-files --others --exclude-standard
    } | sort -u
  )"

  while IFS= read -r path; do
    case "${path}" in
      agent_service/pyproject.toml|agent_service/uv.lock)
        BUILD_AGENT=1
        BUILD_BACKOFFICE=1
        BUILD_PORTAL=1
        ;;
      agent_service/src/agent_service/documents.py|agent_service/src/agent_service/retrieval.py|agent_service/src/agent_service/release_artifacts.py|agent_service/src/agent_service/knowledge_release_gcs.py)
        BUILD_AGENT=1
        BUILD_PORTAL=1
        ;;
      agent_service/src/agent_service/*|agent_service/Dockerfile|data/faq.json)
        BUILD_AGENT=1
        ;;
      data/ops/*)
        BUILD_AGENT=1
        BUILD_BACKOFFICE=1
        ;;
      src/*|pyproject.toml|uv.lock|Dockerfile)
        BUILD_ADAPTER=1
        ;;
      console_frontend/*|console_frontend/Dockerfile|deploy/cloudbuild-console.yaml)
        # Phase G: UI-only changes build the independent console image, not
        # the Backoffice Python image.
        BUILD_CONSOLE=1
        ;;
      agent_service/src/ai_ops_backoffice/*|agent_service/Dockerfile.backoffice)
        BUILD_BACKOFFICE=1
        ;;
      agent_service/src/knowledge_portal/*)
        BUILD_PORTAL=1
        ;;
      agent_service/Dockerfile.portal)
        BUILD_PORTAL=1
        ;;
      services/pdf_converter/Dockerfile.upstream)
        BUILD_CONVERTER=1
        ;;
      deploy/cloudbuild-release.yaml|deploy/release-gcp.sh)
        BUILD_AGENT=1
        BUILD_ADAPTER=1
        BUILD_BACKOFFICE=1
        BUILD_PORTAL=1
        BUILD_CONVERTER=1
        BUILD_CONSOLE=1
        ;;
    esac
  done <<<"${changed_files}"
}

require_cmd git
select_components
if ((BUILD_AGENT + BUILD_ADAPTER + BUILD_BACKOFFICE + BUILD_PORTAL + BUILD_CONVERTER + BUILD_CONSOLE == 0)); then
  fail "No application changes detected. Publish knowledge separately or set RELEASE_COMPONENTS."
fi
if [[ "${RELEASE_DRY_RUN:-0}" == "1" ]]; then
  printf 'agent=%s adapter=%s backoffice=%s portal=%s converter=%s console=%s\n' \
    "${BUILD_AGENT}" "${BUILD_ADAPTER}" "${BUILD_BACKOFFICE}" "${BUILD_PORTAL}" \
    "${BUILD_CONVERTER}" "${BUILD_CONSOLE}"
  exit 0
fi
[[ -n "${PROJECT_ID}" ]] || fail "Set GCP_PROJECT_ID"
require_cmd gcloud
require_cmd curl

BUILD_ONLY="${BUILD_ONLY:-0}"

if [[ "${BUILD_ONLY}" != "1" ]]; then
  PREVIOUS_AGENT_IMAGE=""
  PREVIOUS_ADAPTER_IMAGE=""
  PREVIOUS_BACKOFFICE_IMAGE=""
  PREVIOUS_PORTAL_IMAGE=""
  PREVIOUS_CONVERTER_IMAGE=""
  PREVIOUS_CONSOLE_IMAGE=""
  if [[ "${BUILD_AGENT}" == "1" ]]; then
    PREVIOUS_AGENT_IMAGE="$(
      pin_image_reference "$(current_service_image "${AGENT_SERVICE}")"
    )"
  fi
  if [[ "${BUILD_ADAPTER}" == "1" ]]; then
    PREVIOUS_ADAPTER_IMAGE="$(
      pin_image_reference "$(current_service_image "${ADAPTER_SERVICE}")"
    )"
  fi
  if [[ "${BUILD_BACKOFFICE}" == "1" ]]; then
    PREVIOUS_BACKOFFICE_IMAGE="$(
      pin_image_reference "$(current_service_image "${BACKOFFICE_SERVICE}")"
    )"
  fi
  if [[ "${BUILD_PORTAL}" == "1" ]]; then
    PREVIOUS_PORTAL_IMAGE="$(
      pin_image_reference "$(current_service_image "${PORTAL_SERVICE}")"
    )"
  fi
  if [[ "${BUILD_CONVERTER}" == "1" ]]; then
    PREVIOUS_CONVERTER_IMAGE="$(
      pin_image_reference "$(current_service_image "${CONVERTER_SERVICE}")"
    )"
  fi
  if [[ "${BUILD_CONSOLE}" == "1" && -n "${CONSOLE_SERVICE}" ]]; then
    PREVIOUS_CONSOLE_IMAGE="$(
      pin_image_reference "$(current_service_image "${CONSOLE_SERVICE}")"
    )"
  fi

  rollback_all() {
    rollback_service_image "${AGENT_SERVICE}" "${PREVIOUS_AGENT_IMAGE}"
    rollback_service_image "${ADAPTER_SERVICE}" "${PREVIOUS_ADAPTER_IMAGE}"
    rollback_service_image "${BACKOFFICE_SERVICE}" "${PREVIOUS_BACKOFFICE_IMAGE}"
    rollback_service_image "${PORTAL_SERVICE}" "${PREVIOUS_PORTAL_IMAGE}"
    rollback_service_image "${CONVERTER_SERVICE}" "${PREVIOUS_CONVERTER_IMAGE}"
    if [[ -n "${CONSOLE_SERVICE}" ]]; then
      rollback_service_image "${CONSOLE_SERVICE}" "${PREVIOUS_CONSOLE_IMAGE}"
    fi
  }

  trap 'status=$?; if [[ ${status} -ne 0 ]]; then log "Release failed — attempting rollback"; rollback_all; fi; exit ${status}' ERR
fi

gcloud config set project "${PROJECT_ID}" >/dev/null

if ((BUILD_AGENT + BUILD_ADAPTER + BUILD_BACKOFFICE + BUILD_PORTAL + BUILD_CONVERTER > 0)); then
  log "Submitting one parallel application build"
  gcloud builds submit "${PROJECT_DIR}" \
    --config="${PROJECT_DIR}/deploy/cloudbuild-release.yaml" \
    --substitutions="_BUILD_AGENT=${BUILD_AGENT},_BUILD_ADAPTER=${BUILD_ADAPTER},_BUILD_BACKOFFICE=${BUILD_BACKOFFICE},_BUILD_PORTAL=${BUILD_PORTAL},_BUILD_CONVERTER=${BUILD_CONVERTER},_AGENT_IMAGE=${AGENT_IMAGE},_ADAPTER_IMAGE=${ADAPTER_IMAGE},_BACKOFFICE_IMAGE=${BACKOFFICE_IMAGE},_PORTAL_IMAGE=${PORTAL_IMAGE},_CONVERTER_IMAGE=${CONVERTER_IMAGE},_AGENT_CACHE_IMAGE=${AGENT_CACHE_IMAGE},_ADAPTER_CACHE_IMAGE=${ADAPTER_CACHE_IMAGE},_BACKOFFICE_CACHE_IMAGE=${BACKOFFICE_CACHE_IMAGE},_PORTAL_CACHE_IMAGE=${PORTAL_CACHE_IMAGE},_CONVERTER_CACHE_IMAGE=${CONVERTER_CACHE_IMAGE}" \
    --project="${PROJECT_ID}"
fi

if [[ "${BUILD_CONSOLE}" == "1" ]]; then
  log "Submitting independent console-v2 image build"
  gcloud builds submit "${PROJECT_DIR}" \
    --config="${PROJECT_DIR}/deploy/cloudbuild-console.yaml" \
    --substitutions="_IMAGE=${CONSOLE_IMAGE}" \
    --project="${PROJECT_ID}"
fi

if [[ "${BUILD_AGENT}" == "1" ]]; then AGENT_IMAGE="$(resolve_image_digest "${AGENT_IMAGE}")"; fi
if [[ "${BUILD_ADAPTER}" == "1" ]]; then ADAPTER_IMAGE="$(resolve_image_digest "${ADAPTER_IMAGE}")"; fi
if [[ "${BUILD_BACKOFFICE}" == "1" ]]; then BACKOFFICE_IMAGE="$(resolve_image_digest "${BACKOFFICE_IMAGE}")"; fi
if [[ "${BUILD_PORTAL}" == "1" ]]; then PORTAL_IMAGE="$(resolve_image_digest "${PORTAL_IMAGE}")"; fi
if [[ "${BUILD_CONVERTER}" == "1" ]]; then CONVERTER_IMAGE="$(resolve_image_digest "${CONVERTER_IMAGE}")"; fi
if [[ "${BUILD_CONSOLE}" == "1" ]]; then CONSOLE_IMAGE="$(resolve_image_digest "${CONSOLE_IMAGE}")"; fi

if [[ "${BUILD_ONLY:-0}" == "1" ]]; then
  printf '\nBuild complete (BUILD_ONLY=1 — Cloud Run not updated).\n'
  printf 'Git SHA:       %s\n' "${GIT_SHA}"
  printf 'Agent image:   %s\n' "${AGENT_IMAGE}"
  printf 'Adapter image: %s\n' "${ADAPTER_IMAGE}"
  printf 'Backoffice:    %s\n' "${BACKOFFICE_IMAGE}"
  printf 'Portal:        %s\n' "${PORTAL_IMAGE}"
  printf 'Converter:     %s\n' "${CONVERTER_IMAGE}"
  printf 'Console:       %s\n' "${CONSOLE_IMAGE}"
  exit 0
fi

deploy_service_image() {
  local service="$1"
  local image="$2"
  log "Updating ${service} to ${image}"
  gcloud run services update "${service}" \
    --image="${image}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --quiet >/dev/null
  wait_for_cloud_run_ready "${service}" \
    || fail "${service} did not become Ready"
}

DEPLOY_PIDS=()
if [[ "${BUILD_AGENT}" == "1" ]]; then
  deploy_service_image "${AGENT_SERVICE}" "${AGENT_IMAGE}" &
  DEPLOY_PIDS+=("$!")
fi
if [[ "${BUILD_ADAPTER}" == "1" ]]; then
  deploy_service_image "${ADAPTER_SERVICE}" "${ADAPTER_IMAGE}" &
  DEPLOY_PIDS+=("$!")
fi
if [[ "${BUILD_BACKOFFICE}" == "1" ]]; then
  deploy_service_image "${BACKOFFICE_SERVICE}" "${BACKOFFICE_IMAGE}" &
  DEPLOY_PIDS+=("$!")
fi
if [[ "${BUILD_PORTAL}" == "1" ]]; then
  deploy_service_image "${PORTAL_SERVICE}" "${PORTAL_IMAGE}" &
  DEPLOY_PIDS+=("$!")
fi
if [[ "${BUILD_CONVERTER}" == "1" ]]; then
  deploy_service_image "${CONVERTER_SERVICE}" "${CONVERTER_IMAGE}" &
  DEPLOY_PIDS+=("$!")
fi
if [[ "${BUILD_CONSOLE}" == "1" && -n "${CONSOLE_SERVICE}" ]]; then
  deploy_service_image "${CONSOLE_SERVICE}" "${CONSOLE_IMAGE}" &
  DEPLOY_PIDS+=("$!")
elif [[ "${BUILD_CONSOLE}" == "1" ]]; then
  log "Console image built (${CONSOLE_IMAGE}); set GCP_CONSOLE_SERVICE to deploy the independent UI service"
fi
DEPLOY_FAILED=0
for pid in "${DEPLOY_PIDS[@]}"; do
  if ! wait "${pid}"; then
    DEPLOY_FAILED=1
  fi
done
[[ "${DEPLOY_FAILED}" == "0" ]] \
  || fail "One or more Cloud Run revisions failed; all updates finished before rollback"

ADAPTER_URL=""
if [[ "${BUILD_AGENT}" == "1" || "${BUILD_ADAPTER}" == "1" ]]; then
  ADAPTER_URL="$(gcloud run services describe "${ADAPTER_SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)')"
  wait_for_adapter_readyz "${ADAPTER_URL}" || fail "Adapter /readyz did not succeed"
fi

trap - ERR

printf '\nRelease complete.\n'
printf 'Git SHA:       %s\n' "${GIT_SHA}"
printf 'Agent image:   %s\n' "${AGENT_IMAGE}"
printf 'Adapter image: %s\n' "${ADAPTER_IMAGE}"
printf 'Backoffice:    %s\n' "${BACKOFFICE_IMAGE}"
printf 'Portal:        %s\n' "${PORTAL_IMAGE}"
printf 'Converter:     %s\n' "${CONVERTER_IMAGE}"
printf 'Console:       %s\n' "${CONSOLE_IMAGE}"
if [[ -n "${ADAPTER_URL}" ]]; then
  printf 'Adapter URL:   %s\n' "${ADAPTER_URL}"
  printf 'Smoke:         curl -sS %s/readyz\n' "${ADAPTER_URL}"
fi

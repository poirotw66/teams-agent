#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-itr-aimasteryhub-lab}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
BACKOFFICE_API_SERVICE="${GCP_BACKOFFICE_API_SERVICE:-ai-ops-backoffice-api}"
BACKOFFICE_WORKER_SERVICE="${GCP_BACKOFFICE_WORKER_SERVICE:-ai-ops-backoffice-worker}"
BACKOFFICE_SA_NAME="${GCP_BACKOFFICE_SA:-ai-ops-backoffice}"

BACKOFFICE_SA="${BACKOFFICE_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
BACKOFFICE_IMAGE="${REGISTRY}/ai-ops-backoffice:latest"

OPS_STORE_MODE="${OPS_STORE_MODE:-FIRESTORE}"
FIRESTORE_DATABASE="${GCP_FIRESTORE_DATABASE:-(default)}"

log() {
  printf '[deploy-backoffice] %s\n' "$*"
}

fail() {
  printf '[deploy-backoffice] ERROR: %s\n' "$*" >&2
  exit 1
}

command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI is required."

log "Deploying split AI Ops Backoffice to GCP project: ${PROJECT_ID} (${REGION})"

# 1. Build Backoffice Container Image
log "Building backoffice image ${BACKOFFICE_IMAGE}..."
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --config="deploy/cloudbuild-backoffice.yaml" \
  --substitutions="_IMAGE=${BACKOFFICE_IMAGE}" \
  .

# 2. Deploy Dedicated API Cloud Run Service (Workers Disabled)
log "Deploying dedicated API instance ${BACKOFFICE_API_SERVICE} (AI_OPS_WORKERS_ENABLED=false)..."
gcloud run deploy "${BACKOFFICE_API_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${BACKOFFICE_IMAGE}" \
  --platform="managed" \
  --service-account="${BACKOFFICE_SA}" \
  --set-env-vars="AI_OPS_WORKERS_ENABLED=false,AI_OPS_STORE_MODE=${OPS_STORE_MODE},GCP_PROJECT_ID=${PROJECT_ID},AI_OPS_BACKOFFICE_PORT=8080" \
  --port=8080 \
  --cpu=1 \
  --memory=1Gi \
  --min-instances=0 \
  --max-instances=10 \
  --timeout=300 \
  --no-allow-unauthenticated

# 3. Deploy Dedicated Background Worker Cloud Run Service (Workers Enabled, Dedicated Singleton)
log "Deploying dedicated Worker instance ${BACKOFFICE_WORKER_SERVICE} (AI_OPS_WORKERS_ENABLED=true)..."
gcloud run deploy "${BACKOFFICE_WORKER_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${BACKOFFICE_IMAGE}" \
  --platform="managed" \
  --service-account="${BACKOFFICE_SA}" \
  --command="python" \
  --args="-m,ai_ops_backoffice.worker_main" \
  --set-env-vars="AI_OPS_WORKERS_ENABLED=true,AI_OPS_STORE_MODE=${OPS_STORE_MODE},GCP_PROJECT_ID=${PROJECT_ID},AI_OPS_WORKER_PORT=8080,PORT=8080" \
  --port=8080 \
  --cpu=1 \
  --memory=1Gi \
  --min-instances=1 \
  --max-instances=1 \
  --no-cpu-throttling \
  --timeout=3600 \
  --no-allow-unauthenticated

log "Deployment complete:"
log "  API Service:    $(gcloud run services describe "${BACKOFFICE_API_SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"
log "  Worker Service: $(gcloud run services describe "${BACKOFFICE_WORKER_SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"

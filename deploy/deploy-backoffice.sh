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

ENVIRONMENT="${ENVIRONMENT:-production}"
OPS_STORE_MODE="${OPS_STORE_MODE:-FIRESTORE}"
FIRESTORE_DATABASE="${GCP_FIRESTORE_DATABASE:-(default)}"
BACKOFFICE_AUTH_MODE="${AI_OPS_BACKOFFICE_AUTH_MODE:-${AUTH_MODE:-HEADER}}"
BACKOFFICE_TOKEN="${AI_OPS_BACKOFFICE_TOKEN:-${SERVICE_TOKEN:-}}"
ENTRA_TENANT_ID="${AI_OPS_ENTRA_TENANT_ID:-${ENTRA_TENANT_ID:-}}"
ENTRA_CLIENT_ID="${AI_OPS_ENTRA_CLIENT_ID:-${ENTRA_CLIENT_ID:-}}"

log() {
  printf '[deploy-backoffice] %s\n' "$*"
}

fail() {
  printf '[deploy-backoffice] ERROR: %s\n' "$*" >&2
  exit 1
}

command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI is required."

log "Deploying split AI Ops Backoffice to GCP project: ${PROJECT_ID} (${REGION})"

# 1. Pre-flight Configuration Validation
log "Running pre-flight deployment configuration validation..."
ENVIRONMENT="${ENVIRONMENT}" \
OPS_STORE_MODE="${OPS_STORE_MODE}" \
AI_OPS_STORE_MODE="${OPS_STORE_MODE}" \
GCP_PROJECT_ID="${PROJECT_ID}" \
GOOGLE_CLOUD_PROJECT="${PROJECT_ID}" \
AI_OPS_BACKOFFICE_AUTH_MODE="${BACKOFFICE_AUTH_MODE}" \
AI_OPS_BACKOFFICE_TOKEN="${BACKOFFICE_TOKEN}" \
AI_OPS_ENTRA_TENANT_ID="${ENTRA_TENANT_ID}" \
AI_OPS_ENTRA_CLIENT_ID="${ENTRA_CLIENT_ID}" \
python3 -m ai_ops_backoffice.config_validator --production || fail "Pre-flight deployment configuration validation failed. Please check environment variables."

# Shared environment variables aligned across all deployment instances
SHARED_ENV_VARS="ENVIRONMENT=${ENVIRONMENT},AI_OPS_DEPLOYMENT_ENV=${ENVIRONMENT},OPS_STORE_MODE=${OPS_STORE_MODE},AI_OPS_STORE_MODE=${OPS_STORE_MODE},GCP_PROJECT_ID=${PROJECT_ID},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},AI_OPS_GCP_PROJECT=${PROJECT_ID},AI_OPS_BACKOFFICE_AUTH_MODE=${BACKOFFICE_AUTH_MODE},AI_OPS_BACKOFFICE_TOKEN=${BACKOFFICE_TOKEN},AI_OPS_ENTRA_TENANT_ID=${ENTRA_TENANT_ID},AI_OPS_ENTRA_CLIENT_ID=${ENTRA_CLIENT_ID},OPS_AUDIT_STORE_MODE=${OPS_STORE_MODE},AI_OPS_FAQ_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EXAMPLE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_QUALITY_STORE_MODE=${OPS_STORE_MODE},AI_OPS_SYNC_STORE_MODE=${OPS_STORE_MODE},AI_OPS_BUDGET_STORE_MODE=${OPS_STORE_MODE},AI_OPS_PROMPT_POC_STORE_MODE=${OPS_STORE_MODE},AI_OPS_GOVERNANCE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EVAL_STORE_MODE=${OPS_STORE_MODE},AI_OPS_GATE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_FIXTURE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_JOB_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EXPORT_JOB_STORE_MODE=${OPS_STORE_MODE},AI_OPS_SOURCE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_ARTIFACT_STORAGE_BACKEND=GCS,AI_OPS_EXPORT_CONTENT_BACKEND=GCS,AI_OPS_EXPORT_GCS_BUCKET=${PROJECT_ID}-backoffice-exports"

# 2. Build Backoffice Container Image
log "Building backoffice image ${BACKOFFICE_IMAGE}..."
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --config="deploy/cloudbuild-backoffice.yaml" \
  --substitutions="_IMAGE=${BACKOFFICE_IMAGE}" \
  .

# 3. Deploy Dedicated API Cloud Run Service (Workers Disabled)
log "Deploying dedicated API instance ${BACKOFFICE_API_SERVICE} (AI_OPS_WORKERS_ENABLED=false)..."
gcloud run deploy "${BACKOFFICE_API_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${BACKOFFICE_IMAGE}" \
  --platform="managed" \
  --service-account="${BACKOFFICE_SA}" \
  --set-env-vars="AI_OPS_WORKERS_ENABLED=false,AI_OPS_BACKOFFICE_PORT=8080,PORT=8080,${SHARED_ENV_VARS}" \
  --port=8080 \
  --cpu=1 \
  --memory=1Gi \
  --min-instances=0 \
  --max-instances=10 \
  --timeout=300 \
  --no-allow-unauthenticated

# 4. Deploy Dedicated Background Worker Cloud Run Service (Workers Enabled, Dedicated Singleton)
log "Deploying dedicated Worker instance ${BACKOFFICE_WORKER_SERVICE} (AI_OPS_WORKERS_ENABLED=true)..."
gcloud run deploy "${BACKOFFICE_WORKER_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${BACKOFFICE_IMAGE}" \
  --platform="managed" \
  --service-account="${BACKOFFICE_SA}" \
  --command="python" \
  --args="-m,ai_ops_backoffice.worker_main" \
  --set-env-vars="AI_OPS_WORKERS_ENABLED=true,AI_OPS_WORKER_PORT=8080,PORT=8080,${SHARED_ENV_VARS}" \
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

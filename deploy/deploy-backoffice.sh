#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-itr-aimasteryhub-lab}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
BACKOFFICE_API_SERVICE="${GCP_BACKOFFICE_API_SERVICE:-teams-ai-ops-backoffice}"
BACKOFFICE_WORKER_SERVICE="${GCP_BACKOFFICE_WORKER_SERVICE:-teams-ai-ops-backoffice-worker}"
BACKOFFICE_SA_NAME="${GCP_BACKOFFICE_SA:-ai-ops-backoffice}"

BACKOFFICE_SA="${BACKOFFICE_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
BACKOFFICE_IMAGE="${REGISTRY}/teams-ai-ops-backoffice:latest"

ENVIRONMENT="${ENVIRONMENT:-production}"
OPS_STORE_MODE="${OPS_STORE_MODE:-FIRESTORE}"
BACKOFFICE_AUTH_MODE="${AI_OPS_BACKOFFICE_AUTH_MODE:-${AUTH_MODE:-ENTRA}}"
ENTRA_TENANT_ID="${AI_OPS_ENTRA_TENANT_ID:-${ENTRA_TENANT_ID:-}}"
ENTRA_CLIENT_ID="${AI_OPS_ENTRA_CLIENT_ID:-${ENTRA_CLIENT_ID:-}}"
ARTIFACT_GCS_BUCKET="${AI_OPS_ARTIFACT_GCS_BUCKET:-${PROJECT_ID}-backoffice-originals}"
EXPORT_GCS_BUCKET="${AI_OPS_EXPORT_GCS_BUCKET:-${PROJECT_ID}-backoffice-exports}"
ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"
BACKOFFICE_TOKEN_SECRET="${GCP_BACKOFFICE_TOKEN_SECRET:-teams-ai-ops-backoffice-token}"
SOURCE_DELEGATION_SECRET="${GCP_SOURCE_DELEGATION_SECRET:-teams-agent-knowledge-delegation-secret}"
BACKOFFICE_TOKEN_SEED="${AI_OPS_BACKOFFICE_TOKEN:-${SERVICE_TOKEN:-}}"
SOURCE_DELEGATION_SEED="${AI_OPS_SOURCE_DELEGATION_SECRET:-${RAG_ASSET_SIGNING_KEY:-}}"

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf '[deploy-backoffice] %s\n' "$*"
}

fail() {
  printf '[deploy-backoffice] ERROR: %s\n' "$*" >&2
  exit 1
}

# shellcheck source=lib/source-api-wiring.sh
source "${PROJECT_DIR}/deploy/lib/source-api-wiring.sh"

command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI is required."

log "Deploying split AI Ops Backoffice to GCP project: ${PROJECT_ID} (${REGION})"

# 1. Pre-flight Configuration Validation
log "Running pre-flight deployment configuration validation..."
ENVIRONMENT="${ENVIRONMENT}" \
AI_OPS_STORE_MODE="${OPS_STORE_MODE}" \
GCP_PROJECT_ID="${PROJECT_ID}" \
GOOGLE_CLOUD_PROJECT="${PROJECT_ID}" \
AI_OPS_BACKOFFICE_AUTH_MODE="${BACKOFFICE_AUTH_MODE}" \
AI_OPS_ENTRA_TENANT_ID="${ENTRA_TENANT_ID}" \
AI_OPS_ENTRA_CLIENT_ID="${ENTRA_CLIENT_ID}" \
AI_OPS_ARTIFACT_STORAGE_BACKEND=GCS \
AI_OPS_ARTIFACT_GCS_BUCKET="${ARTIFACT_GCS_BUCKET}" \
AI_OPS_EXPORT_GCS_BUCKET="${EXPORT_GCS_BUCKET}" \
python3 -m ai_ops_backoffice.config_validator --production || fail "Pre-flight deployment configuration validation failed. Please check environment variables."

log "Confirm Source API secrets (existing values are kept)"
ensure_source_api_secrets "${BACKOFFICE_TOKEN_SEED}" "${SOURCE_DELEGATION_SEED}"
grant_source_api_secret_access "${BACKOFFICE_SA}"

# Shared environment variables aligned across all deployment instances.
# Tokens stay in Secret Manager; never put them in --set-env-vars.
SHARED_ENV_VARS="ENVIRONMENT=${ENVIRONMENT},AI_OPS_DEPLOYMENT_ENV=${ENVIRONMENT},OPS_STORE_MODE=${OPS_STORE_MODE},AI_OPS_STORE_MODE=${OPS_STORE_MODE},GCP_PROJECT_ID=${PROJECT_ID},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},AI_OPS_GCP_PROJECT=${PROJECT_ID},AI_OPS_BACKOFFICE_AUTH_MODE=${BACKOFFICE_AUTH_MODE},AI_OPS_ENTRA_TENANT_ID=${ENTRA_TENANT_ID},AI_OPS_ENTRA_CLIENT_ID=${ENTRA_CLIENT_ID},OPS_AUDIT_STORE_MODE=${OPS_STORE_MODE},AI_OPS_FAQ_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EXAMPLE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_QUALITY_STORE_MODE=${OPS_STORE_MODE},AI_OPS_SYNC_STORE_MODE=${OPS_STORE_MODE},AI_OPS_BUDGET_STORE_MODE=${OPS_STORE_MODE},AI_OPS_PROMPT_POC_STORE_MODE=${OPS_STORE_MODE},AI_OPS_GOVERNANCE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EVAL_STORE_MODE=${OPS_STORE_MODE},AI_OPS_GATE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_FIXTURE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_JOB_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EXPORT_JOB_STORE_MODE=${OPS_STORE_MODE},AI_OPS_SOURCE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_ARTIFACT_STORAGE_BACKEND=GCS,AI_OPS_ARTIFACT_GCS_BUCKET=${ARTIFACT_GCS_BUCKET},AI_OPS_EXPORT_CONTENT_BACKEND=GCS,AI_OPS_EXPORT_GCS_BUCKET=${EXPORT_GCS_BUCKET},KNOWLEDGE_PORTAL_UPSTREAM_TIMEOUT_SECONDS=540"
BACKOFFICE_SECRETS="AI_OPS_BACKOFFICE_TOKEN=${BACKOFFICE_TOKEN_SECRET}:latest,AI_OPS_SOURCE_DELEGATION_SECRET=${SOURCE_DELEGATION_SECRET}:latest"
BACKOFFICE_PLAINTEXT_SECRET_KEYS="AI_OPS_BACKOFFICE_TOKEN,AI_OPS_SOURCE_DELEGATION_SECRET"

# 2. Build Backoffice Container Image
log "Building backoffice image ${BACKOFFICE_IMAGE}..."
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --config="deploy/cloudbuild-backoffice.yaml" \
  --substitutions="_IMAGE=${BACKOFFICE_IMAGE}" \
  .

# 3. Deploy Dedicated API Cloud Run Service (Workers Disabled)
log "Deploying dedicated API instance ${BACKOFFICE_API_SERVICE} (AI_OPS_WORKERS_ENABLED=false)..."
deploy_cloud_run_preserving_runtime \
  "${BACKOFFICE_API_SERVICE}" \
  "${BACKOFFICE_IMAGE}" \
  "AI_OPS_WORKERS_ENABLED=false,AI_OPS_BACKOFFICE_PORT=8080,${SHARED_ENV_VARS}" \
  "${BACKOFFICE_SECRETS}" \
  "${BACKOFFICE_PLAINTEXT_SECRET_KEYS}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform="managed" \
  --service-account="${BACKOFFICE_SA}" \
  --port=8080 \
  --cpu=1 \
  --memory=1Gi \
  --concurrency=20 \
  --min-instances=0 \
  --max-instances=10 \
  --timeout=600 \
  --allow-unauthenticated

# 4. Deploy Dedicated Background Worker Cloud Run Service (Workers Enabled, Dedicated Singleton)
log "Deploying dedicated Worker instance ${BACKOFFICE_WORKER_SERVICE} (AI_OPS_WORKERS_ENABLED=true)..."
deploy_cloud_run_preserving_runtime \
  "${BACKOFFICE_WORKER_SERVICE}" \
  "${BACKOFFICE_IMAGE}" \
  "AI_OPS_WORKERS_ENABLED=true,AI_OPS_WORKER_PORT=8080,${SHARED_ENV_VARS}" \
  "${BACKOFFICE_SECRETS}" \
  "${BACKOFFICE_PLAINTEXT_SECRET_KEYS}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform="managed" \
  --service-account="${BACKOFFICE_SA}" \
  --command="python" \
  --args="-m,ai_ops_backoffice.worker_main" \
  --port=8080 \
  --cpu=1 \
  --memory=1Gi \
  --min-instances=1 \
  --max-instances=1 \
  --no-cpu-throttling \
  --timeout=3600 \
  --no-allow-unauthenticated

# Adapter is usually deployed first. Always re-wire Source API after Backoffice
# exists so citation preview delivery is not left half-configured.
ensure_source_api_wiring "${BACKOFFICE_TOKEN_SEED}" "${SOURCE_DELEGATION_SEED}"

log "Deployment complete:"
log "  API Service:    $(gcloud run services describe "${BACKOFFICE_API_SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"
log "  Worker Service: $(gcloud run services describe "${BACKOFFICE_WORKER_SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"

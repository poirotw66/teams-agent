#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-itr-aimasteryhub-lab}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
BACKOFFICE_API_SERVICE="${GCP_BACKOFFICE_API_SERVICE:-teams-ai-ops-backoffice}"
BACKOFFICE_WORKER_SERVICE="${GCP_BACKOFFICE_WORKER_SERVICE:-teams-ai-ops-backoffice-worker}"
PORTAL_SERVICE="${GCP_PORTAL_SERVICE:-teams-knowledge-portal}"
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
export ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"
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

# shellcheck disable=SC1091
source "${PROJECT_DIR}/deploy/lib/source-api-wiring.sh"
# shellcheck disable=SC1091
source "${PROJECT_DIR}/deploy/lib/vertex-revision-contract.sh"

GEMINI_API_BACKEND="VERTEX_AI"
# Explicit Vertex target only. Do not default to PROJECT_ID or "global".
VERTEX_AI_PROJECT="${VERTEX_AI_PROJECT:-}"
VERTEX_AI_CHAT_LOCATION="${VERTEX_AI_CHAT_LOCATION:-}"
VERTEX_AI_EMBEDDING_LOCATION="${VERTEX_AI_EMBEDDING_LOCATION:-}"
require_value() { [[ -n "${1:-}" ]] || fail "Missing required value: ${2}"; }
require_explicit_vertex_project
require_approved_vertex_location "${VERTEX_AI_CHAT_LOCATION}" "VERTEX_AI_CHAT_LOCATION"
require_approved_vertex_location "${VERTEX_AI_EMBEDDING_LOCATION}" "VERTEX_AI_EMBEDDING_LOCATION"

command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI is required."
gcloud projects add-iam-policy-binding "${VERTEX_AI_PROJECT}" \
  --member="serviceAccount:${BACKOFFICE_SA}" \
  --role=roles/aiplatform.user \
  --condition=None >/dev/null

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
# Cloud Console copy uses in-process=false + console surface. Keep
# LOCAL_SANDBOX so publish/unpublish stay on today's write path; CLOUD_FORMAL
# without formal identity would 403 knowledge.publish.
KNOWLEDGE_CONSOLE_ENV="AI_OPS_KNOWLEDGE_IN_PROCESS=false,AI_OPS_CONSOLE_SURFACE=CLOUD,AI_OPS_KNOWLEDGE_WORKSPACE_MODE=LOCAL_SANDBOX"
VERTEX_ENV_VARS="GEMINI_API_BACKEND=${GEMINI_API_BACKEND},VERTEX_AI_PROJECT=${VERTEX_AI_PROJECT},VERTEX_AI_CHAT_LOCATION=${VERTEX_AI_CHAT_LOCATION},VERTEX_AI_EMBEDDING_LOCATION=${VERTEX_AI_EMBEDDING_LOCATION},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${VERTEX_AI_PROJECT},GOOGLE_CLOUD_LOCATION=${VERTEX_AI_CHAT_LOCATION}"
SHARED_ENV_VARS="ENVIRONMENT=${ENVIRONMENT},AI_OPS_DEPLOYMENT_ENV=${ENVIRONMENT},OPS_STORE_MODE=${OPS_STORE_MODE},AI_OPS_STORE_MODE=${OPS_STORE_MODE},GCP_PROJECT_ID=${PROJECT_ID},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},AI_OPS_GCP_PROJECT=${PROJECT_ID},AI_OPS_BACKOFFICE_AUTH_MODE=${BACKOFFICE_AUTH_MODE},AI_OPS_ENTRA_TENANT_ID=${ENTRA_TENANT_ID},AI_OPS_ENTRA_CLIENT_ID=${ENTRA_CLIENT_ID},OPS_AUDIT_STORE_MODE=${OPS_STORE_MODE},AI_OPS_FAQ_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EXAMPLE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_QUALITY_STORE_MODE=${OPS_STORE_MODE},AI_OPS_SYNC_STORE_MODE=${OPS_STORE_MODE},AI_OPS_BUDGET_STORE_MODE=${OPS_STORE_MODE},AI_OPS_PROMPT_POC_STORE_MODE=${OPS_STORE_MODE},AI_OPS_GOVERNANCE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EVAL_STORE_MODE=${OPS_STORE_MODE},AI_OPS_GATE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_FIXTURE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_JOB_STORE_MODE=${OPS_STORE_MODE},AI_OPS_EXPORT_JOB_STORE_MODE=${OPS_STORE_MODE},AI_OPS_SOURCE_STORE_MODE=${OPS_STORE_MODE},AI_OPS_ARTIFACT_STORAGE_BACKEND=GCS,AI_OPS_ARTIFACT_GCS_BUCKET=${ARTIFACT_GCS_BUCKET},AI_OPS_EXPORT_CONTENT_BACKEND=GCS,AI_OPS_EXPORT_GCS_BUCKET=${EXPORT_GCS_BUCKET},KNOWLEDGE_PORTAL_UPSTREAM_TIMEOUT_SECONDS=540,${VERTEX_ENV_VARS},${KNOWLEDGE_CONSOLE_ENV}"
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
unmount_developer_api_key_secrets "${BACKOFFICE_API_SERVICE}"
assert_bu_vertex_revision "${BACKOFFICE_API_SERVICE}"

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
unmount_developer_api_key_secrets "${BACKOFFICE_WORKER_SERVICE}"
assert_bu_vertex_revision "${BACKOFFICE_WORKER_SERVICE}"

wire_backoffice_remote_portal() {
  if ! cloud_run_service_exists "${PORTAL_SERVICE}"; then
    log "警告：尚未部署 ${PORTAL_SERVICE}，無法寫入 Portal URL。Backoffice 不會假裝本機 in-process Portal。"
    return 0
  fi
  local portal_url
  portal_url="$(gcloud run services describe "${PORTAL_SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)')"
  if [[ -z "${portal_url}" ]]; then
    log "警告：${PORTAL_SERVICE} 沒有 URL，略過 Portal 接線。"
    return 0
  fi
  log "接上遠端 Knowledge Portal：${portal_url}"
  gcloud run services add-iam-policy-binding "${PORTAL_SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${BACKOFFICE_SA}" \
    --role=roles/run.invoker >/dev/null || true
  local portal_env="KNOWLEDGE_PORTAL_PUBLIC_URL=${portal_url},KNOWLEDGE_PORTAL_INTERNAL_URL=${portal_url},KNOWLEDGE_PORTAL_UPSTREAM_AUTH_MODE=GOOGLE_ID_TOKEN"
  _update_cloud_run_runtime "${BACKOFFICE_API_SERVICE}" "${portal_env}" ""
  _update_cloud_run_runtime "${BACKOFFICE_WORKER_SERVICE}" "${portal_env}" ""
  unmount_developer_api_key_secrets "${BACKOFFICE_API_SERVICE}"
  unmount_developer_api_key_secrets "${BACKOFFICE_WORKER_SERVICE}"
  assert_bu_vertex_revision "${BACKOFFICE_API_SERVICE}"
  assert_bu_vertex_revision "${BACKOFFICE_WORKER_SERVICE}"
}

# Adapter is usually deployed first. Always re-wire Source API after Backoffice
# exists so citation preview delivery is not left half-configured.
ensure_source_api_wiring "${BACKOFFICE_TOKEN_SEED}" "${SOURCE_DELEGATION_SEED}"
wire_backoffice_remote_portal

log "Deployment complete:"
log "  API Service:    $(gcloud run services describe "${BACKOFFICE_API_SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"
log "  Worker Service: $(gcloud run services describe "${BACKOFFICE_WORKER_SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"

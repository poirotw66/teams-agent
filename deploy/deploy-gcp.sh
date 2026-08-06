#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-itr-aimasteryhub-lab}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
AGENT_SERVICE="${GCP_AGENT_SERVICE:-teams-rag-agent}"
ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"
AGENT_SA_NAME="${GCP_AGENT_SA:-teams-rag-agent}"
ADAPTER_SA_NAME="${GCP_ADAPTER_SA:-teams-agent-adapter}"

AGENT_SA="${AGENT_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
ADAPTER_SA="${ADAPTER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
AGENT_IMAGE="${REGISTRY}/${AGENT_SERVICE}:latest"
ADAPTER_IMAGE="${REGISTRY}/${ADAPTER_SERVICE}:latest"

GOOGLE_API_SECRET="teams-agent-google-api-key"
BOT_CLIENT_SECRET="teams-agent-bot-client-secret"
ASSET_SIGNING_SECRET="teams-agent-asset-signing-key"

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

env_value() {
  local file="$1"
  local key="$2"
  awk -v target="${key}" '
    index($0, target "=") == 1 {
      sub("^[^=]*=", "")
      print
      exit
    }
  ' "${file}"
}

require_value() {
  local value="$1"
  local name="$2"
  [[ -n "${value}" ]] || fail "缺少 ${name}"
}

ensure_service_account() {
  local name="$1"
  local display_name="$2"
  if ! gcloud iam service-accounts describe \
    "${name}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${name}" \
      --display-name="${display_name}" \
      --project="${PROJECT_ID}"
  fi
}

upsert_secret() {
  local name="$1"
  local value="$2"
  if gcloud secrets describe "${name}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
    printf '%s' "${value}" | gcloud secrets versions add "${name}" \
      --data-file=- \
      --project="${PROJECT_ID}" >/dev/null
  else
    printf '%s' "${value}" | gcloud secrets create "${name}" \
      --replication-policy=automatic \
      --data-file=- \
      --project="${PROJECT_ID}" >/dev/null
  fi
}

cd "${PROJECT_DIR}"

command -v gcloud >/dev/null 2>&1 || fail "找不到 gcloud CLI"
gcloud auth list --filter=status:ACTIVE --format='value(account)' \
  | grep -q . || fail "請先執行 gcloud auth login --update-adc"

GOOGLE_API_KEY_VALUE="$(env_value agent_service/.env GOOGLE_API_KEY)"
BOT_CLIENT_ID="$(env_value .env CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID)"
BOT_CLIENT_SECRET_VALUE="$(env_value .env CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET)"
BOT_TENANT_ID="$(env_value .env CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID)"
ASSET_SIGNING_KEY_VALUE="$(env_value .env RAG_ASSET_SIGNING_KEY)"
RAG_MODEL="$(env_value agent_service/.env RAG_MODEL)"
RAG_EMBEDDING_MODEL="$(env_value agent_service/.env RAG_EMBEDDING_MODEL)"
RAG_ALLOWED_TENANTS="$(env_value agent_service/.env RAG_ALLOWED_TENANTS)"

require_value "${GOOGLE_API_KEY_VALUE}" "agent_service/.env GOOGLE_API_KEY"
require_value "${BOT_CLIENT_ID}" ".env Bot Client ID"
require_value "${BOT_CLIENT_SECRET_VALUE}" ".env Bot Client Secret"
require_value "${BOT_TENANT_ID}" ".env Bot Tenant ID"
require_value "${ASSET_SIGNING_KEY_VALUE}" ".env RAG_ASSET_SIGNING_KEY"
require_value "${RAG_MODEL}" "agent_service/.env RAG_MODEL"
require_value "${RAG_EMBEDDING_MODEL}" "agent_service/.env RAG_EMBEDDING_MODEL"
[[ -f data/index/chunks.json ]] || fail "缺少 data/index/chunks.json，請先執行 uv run rag-index"

log "設定專案並啟用 API"
gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  iamcredentials.googleapis.com \
  --project="${PROJECT_ID}" >/dev/null

log "建立 Artifact Registry 與 Service Accounts"
if ! gcloud artifacts repositories describe "${REPOSITORY}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Teams AI Agent container images" \
    --project="${PROJECT_ID}"
fi
ensure_service_account "${AGENT_SA_NAME}" "Teams LangGraph RAG Agent"
ensure_service_account "${ADAPTER_SA_NAME}" "Teams Bot Adapter"

log "同步 Secret Manager secrets"
upsert_secret "${GOOGLE_API_SECRET}" "${GOOGLE_API_KEY_VALUE}"
upsert_secret "${BOT_CLIENT_SECRET}" "${BOT_CLIENT_SECRET_VALUE}"
upsert_secret "${ASSET_SIGNING_SECRET}" "${ASSET_SIGNING_KEY_VALUE}"

gcloud secrets add-iam-policy-binding "${GOOGLE_API_SECRET}" \
  --member="serviceAccount:${AGENT_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="${PROJECT_ID}" >/dev/null
for secret in "${BOT_CLIENT_SECRET}" "${ASSET_SIGNING_SECRET}"; do
  gcloud secrets add-iam-policy-binding "${secret}" \
    --member="serviceAccount:${ADAPTER_SA}" \
    --role=roles/secretmanager.secretAccessor \
    --project="${PROJECT_ID}" >/dev/null
done

log "建置 LangGraph Agent image"
gcloud builds submit . \
  --config=deploy/cloudbuild-agent.yaml \
  --substitutions="_IMAGE=${AGENT_IMAGE}" \
  --project="${PROJECT_ID}"

log "部署 private LangGraph Agent"
gcloud run deploy "${AGENT_SERVICE}" \
  --image="${AGENT_IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --platform=managed \
  --service-account="${AGENT_SA}" \
  --no-allow-unauthenticated \
  --execution-environment=gen2 \
  --port=8080 \
  --cpu=1 \
  --memory=2Gi \
  --concurrency=8 \
  --timeout=90 \
  --min=0 \
  --max=3 \
  --set-env-vars="LOG_LEVEL=INFO,RAG_DATA_DIR=/app/data,RAG_INDEX_PATH=/app/data/index/chunks.json,RAG_AUTO_BUILD_INDEX=false,RAG_MODEL=${RAG_MODEL},RAG_EMBEDDING_MODEL=${RAG_EMBEDDING_MODEL},RAG_ALLOWED_TENANTS=${RAG_ALLOWED_TENANTS},RAG_MAX_IMAGES=2,KNOWLEDGE_SERVICE_MODE=HYBRID,TICKET_SERVICE_MODE=DISABLED,CONVERSATION_REPOSITORY_MODE=MEMORY,FEEDBACK_ENABLED=true" \
  --set-secrets="GOOGLE_API_KEY=${GOOGLE_API_SECRET}:latest"
  # KNOWLEDGE_SERVICE_MODE/TICKET_SERVICE_MODE/CONVERSATION_REPOSITORY_MODE/
  # FEEDBACK_ENABLED above are set explicitly even though they match the
  # RagSettings code defaults (spec §16), so this deploy is self-documenting
  # about which mode is running in production. To enable the ticket
  # integration, add TICKET_SERVICE_MODE=HTTP, TICKET_SERVICE_BASE_URL=...
  # to --set-env-vars and TICKET_SERVICE_TOKEN=<secret>:latest to
  # --set-secrets (spec §17: it is a credential, never a plain env var).
  # See deploy/README.md for the full list of tunable Agent Service env
  # vars and which Cloud Run knobs (concurrency/CPU/memory/timeout) are
  # worth adjusting once load-test data (spec §16) justifies it.

AGENT_URL="$(gcloud run services describe "${AGENT_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"

gcloud run services add-iam-policy-binding "${AGENT_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${ADAPTER_SA}" \
  --role=roles/run.invoker >/dev/null

log "建置 Teams Adapter image"
gcloud builds submit . \
  --config=deploy/cloudbuild-adapter.yaml \
  --substitutions="_IMAGE=${ADAPTER_IMAGE}" \
  --project="${PROJECT_ID}"

log "部署 public Teams Adapter"
gcloud run deploy "${ADAPTER_SERVICE}" \
  --image="${ADAPTER_IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --platform=managed \
  --service-account="${ADAPTER_SA}" \
  --allow-unauthenticated \
  --execution-environment=gen2 \
  --port=8080 \
  --cpu=1 \
  --memory=512Mi \
  --concurrency=40 \
  --timeout=90 \
  --min=0 \
  --max=3 \
  --set-env-vars="LOG_LEVEL=INFO,AGENT_MODE=api,AGENT_API_URL=${AGENT_URL}/agent/chat,AGENT_API_AUTH_MODE=google_id_token,AGENT_API_AUDIENCE=${AGENT_URL},AGENT_API_TIMEOUT_SECONDS=30,CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID=${BOT_CLIENT_ID},CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID=${BOT_TENANT_ID},RAG_ASSET_DIR=/app/data/assets,RAG_ASSET_URL_TTL_SECONDS=3600,RAG_ASSET_MAX_DIMENSION=1024,RAG_ASSET_MAX_BYTES=1000000" \
  --set-secrets="CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET=${BOT_CLIENT_SECRET}:latest,RAG_ASSET_SIGNING_KEY=${ASSET_SIGNING_SECRET}:latest"

ADAPTER_URL="$(gcloud run services describe "${ADAPTER_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"

log "設定 Adapter public image base URL"
gcloud run services update "${ADAPTER_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --update-env-vars="BOT_PUBLIC_BASE_URL=${ADAPTER_URL}" >/dev/null

printf '\nDeployment complete.\n'
printf 'Agent URL:   %s\n' "${AGENT_URL}"
printf 'Adapter URL: %s\n' "${ADAPTER_URL}"
printf 'Azure Bot Messaging endpoint: %s/api/messages\n' "${ADAPTER_URL}"

#!/usr/bin/env bash

set -Eeuo pipefail

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

# Conversation Repository (spec §10.3). Cloud Run scales to zero and routes
# across instances, so MEMORY/FILE cannot hold conversation context here --
# this deploy always uses the managed Firestore backend.
FIRESTORE_DATABASE="${GCP_FIRESTORE_DATABASE:-(default)}"
FIRESTORE_LOCATION="${GCP_FIRESTORE_LOCATION:-${REGION}}"
FIRESTORE_COLLECTION="${GCP_FIRESTORE_COLLECTION:-conversations}"
HANDOFF_FIRESTORE_COLLECTION="${GCP_HANDOFF_FIRESTORE_COLLECTION:-handoffs}"
KNOWLEDGE_BACKEND_STATE_COLLECTION="${GCP_KNOWLEDGE_BACKEND_STATE_COLLECTION:-runtime_config}"
GEMINI_FILE_SEARCH_STORE="${GEMINI_FILE_SEARCH_STORE:-fileSearchStores/helpdeskstore-1p3gu83qot1s}"
GEMINI_FILE_SEARCH_MODEL="${GEMINI_FILE_SEARCH_MODEL:-gemini-2.5-flash}"
# Production defaults fail closed once File Search store metadata is migrated.
GEMINI_FILE_SEARCH_ENFORCE_ACL="${GEMINI_FILE_SEARCH_ENFORCE_ACL:-true}"
RAG_REQUIRE_FILE_SEARCH_ACL="${RAG_REQUIRE_FILE_SEARCH_ACL:-true}"
# Playground backend switching must not mutate the shared production runtime config.
KNOWLEDGE_BACKEND_ADMIN_ENABLED="${KNOWLEDGE_BACKEND_ADMIN_ENABLED:-false}"
TICKET_REQUEST_DEDUPE_MODE="${TICKET_REQUEST_DEDUPE_MODE:-FIRESTORE}"
TICKET_REQUEST_DEDUPE_COLLECTION="${TICKET_REQUEST_DEDUPE_COLLECTION:-ticket_request_ledger}"

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

if [[ "${TERRAFORM_MANAGED:-0}" == "1" ]]; then
  fail "Project is Terraform-managed. Run infra/terraform apply for shape, inject secrets separately, then deploy/release-gcp.sh for images. Unset TERRAFORM_MANAGED only if you intentionally want a full legacy deploy."
fi

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

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
BOT_CLIENT_ID="${BOT_CLIENT_ID:-$(env_value .env CLIENT_ID)}"
BOT_CLIENT_SECRET_VALUE="${BOT_CLIENT_SECRET_VALUE:-$(env_value .env CLIENT_SECRET)}"
BOT_TENANT_ID="${BOT_TENANT_ID:-$(env_value .env TENANT_ID)}"
ASSET_SIGNING_KEY_VALUE="$(env_value .env RAG_ASSET_SIGNING_KEY)"
RAG_MODEL="$(env_value agent_service/.env RAG_MODEL)"
AGENT_MODEL="$(env_value agent_service/.env AGENT_MODEL)"
RAG_EMBEDDING_MODEL="$(env_value agent_service/.env RAG_EMBEDDING_MODEL)"
RAG_ALLOWED_TENANTS="$(env_value agent_service/.env RAG_ALLOWED_TENANTS)"

require_value "${GOOGLE_API_KEY_VALUE}" "agent_service/.env GOOGLE_API_KEY"
require_value "${BOT_CLIENT_ID}" ".env CLIENT_ID"
require_value "${BOT_CLIENT_SECRET_VALUE}" ".env CLIENT_SECRET"
require_value "${BOT_TENANT_ID}" ".env TENANT_ID"
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
  firestore.googleapis.com \
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

log "確認 Firestore database 與 Conversation TTL policy"
if ! gcloud firestore databases describe \
  --database="${FIRESTORE_DATABASE}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  log "建立 Firestore native database (${FIRESTORE_DATABASE} @ ${FIRESTORE_LOCATION})"
  gcloud firestore databases create \
    --database="${FIRESTORE_DATABASE}" \
    --location="${FIRESTORE_LOCATION}" \
    --type=firestore-native \
    --project="${PROJECT_ID}" >/dev/null
fi

# Conversation sessions roll over after CONVERSATION_TIMEOUT_HOURS, while the
# Agent Service writes `expiresAt` using CONVERSATION_RETENTION_DAYS. These TTL
# policies delete retained data later so the store does not grow without
# bound. `messages` is the subcollection under each conversation, addressed
# as its own collection group.
#
# TTL is a retention mechanism, NOT the timeout mechanism: collection lags
# by up to ~24h, and the Agent Service re-checks lastActivityAt on every
# read, so a not-yet-collected conversation is still treated as expired.
for collection_group in "${FIRESTORE_COLLECTION}" "${FIRESTORE_COLLECTION}_keys" messages; do
  gcloud firestore fields ttls update expiresAt \
    --collection-group="${collection_group}" \
    --database="${FIRESTORE_DATABASE}" \
    --project="${PROJECT_ID}" \
    --enable-ttl \
    --async \
    --quiet >/dev/null 2>&1 \
    || log "警告：無法設定 ${collection_group} 的 TTL policy，請手動確認"
done

# Phase 2: Handoff session timeout is enforced by the application through
# sessionExpiresAt. Firestore TTL only applies the separate 730-day retention
# policy to case and audit-event documents.
for collection_group in "${HANDOFF_FIRESTORE_COLLECTION}" "${HANDOFF_FIRESTORE_COLLECTION}_events"; do
  gcloud firestore fields ttls update retentionExpiresAt \
    --collection-group="${collection_group}" \
    --database="${FIRESTORE_DATABASE}" \
    --project="${PROJECT_ID}" \
    --enable-ttl \
    --async \
    --quiet >/dev/null 2>&1 \
    || log "警告：無法設定 ${collection_group} 的 Handoff TTL policy，請手動確認"
done

# roles/datastore.user covers Firestore document read/write for the Agent
# Service's own service account. The Adapter never touches Firestore.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${AGENT_SA}" \
  --role=roles/datastore.user \
  --condition=None >/dev/null

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
  --set-env-vars="LOG_LEVEL=INFO,RAG_DATA_DIR=/app/data,RAG_INDEX_PATH=/app/data/index/chunks.json,RAG_AUTO_BUILD_INDEX=false,RAG_MODEL=${RAG_MODEL},AGENT_MODEL=${AGENT_MODEL},RAG_EMBEDDING_MODEL=${RAG_EMBEDDING_MODEL},RAG_ALLOWED_TENANTS=${RAG_ALLOWED_TENANTS},RAG_MAX_IMAGES=2,KNOWLEDGE_SERVICE_MODE=HYBRID,GEMINI_FILE_SEARCH_STORE=${GEMINI_FILE_SEARCH_STORE},GEMINI_FILE_SEARCH_MODEL=${GEMINI_FILE_SEARCH_MODEL},GEMINI_FILE_SEARCH_ENFORCE_ACL=${GEMINI_FILE_SEARCH_ENFORCE_ACL},RAG_REQUIRE_FILE_SEARCH_ACL=${RAG_REQUIRE_FILE_SEARCH_ACL},KNOWLEDGE_BACKEND_STATE_MODE=FIRESTORE,KNOWLEDGE_BACKEND_STATE_COLLECTION=${KNOWLEDGE_BACKEND_STATE_COLLECTION},KNOWLEDGE_BACKEND_ADMIN_ENABLED=${KNOWLEDGE_BACKEND_ADMIN_ENABLED},TICKET_REQUEST_DEDUPE_MODE=${TICKET_REQUEST_DEDUPE_MODE},TICKET_REQUEST_DEDUPE_COLLECTION=${TICKET_REQUEST_DEDUPE_COLLECTION},TICKET_SERVICE_MODE=DISABLED,CONVERSATION_REPOSITORY_MODE=FIRESTORE,CONVERSATION_FIRESTORE_COLLECTION=${FIRESTORE_COLLECTION},CONVERSATION_RETENTION_DAYS=730,HANDOFF_REPOSITORY_MODE=FIRESTORE,HANDOFF_FIRESTORE_COLLECTION=${HANDOFF_FIRESTORE_COLLECTION},HANDOFF_DEMO_TIMEOUT_HOURS=24,HANDOFF_RETENTION_DAYS=730,FEEDBACK_ENABLED=true" \
  --set-secrets="GOOGLE_API_KEY=${GOOGLE_API_SECRET}:latest"
  # KNOWLEDGE_SERVICE_MODE/TICKET_SERVICE_MODE/CONVERSATION_REPOSITORY_MODE/
  # FEEDBACK_ENABLED above are set explicitly so this deploy is
  # self-documenting about which mode is running in production (spec §16).
  # CONVERSATION_REPOSITORY_MODE deliberately DIFFERS from the RagSettings
  # default of MEMORY: MEMORY is right for local dev but loses conversation
  # context whenever Cloud Run recycles an instance (spec §10.1's 連續問答
  # and 使用者補充資訊 would silently break). Firestore project and
  # database are left unset so Application Default Credentials resolve them
  # to this service's own project and the (default) database. To enable the
  # ticket
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
  --set-env-vars="LOG_LEVEL=INFO,AGENT_MODE=api,AGENT_API_URL=${AGENT_URL}/agent/chat,AGENT_API_AUTH_MODE=google_id_token,AGENT_API_AUDIENCE=${AGENT_URL},AGENT_API_TIMEOUT_SECONDS=30,CLIENT_ID=${BOT_CLIENT_ID},TENANT_ID=${BOT_TENANT_ID},TEAMS_INBOUND_AUTH_MODE=both,RAG_ASSET_DIR=/app/data/assets,RAG_ASSET_URL_TTL_SECONDS=3600,RAG_ASSET_MAX_DIMENSION=1024,RAG_ASSET_MAX_BYTES=1000000" \
  --set-secrets="CLIENT_SECRET=${BOT_CLIENT_SECRET}:latest,RAG_ASSET_SIGNING_KEY=${ASSET_SIGNING_SECRET}:latest"

ADAPTER_URL="$(gcloud run services describe "${ADAPTER_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"

log "設定 Adapter public image base URL"
gcloud run services update "${ADAPTER_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --update-env-vars="BOT_PUBLIC_BASE_URL=${ADAPTER_URL}" >/dev/null

# If the optional mock ticket UAT service is already deployed, re-wire it.
# deploy-gcp intentionally starts the Agent with TICKET_SERVICE_MODE=DISABLED;
# without this restore step a plain redeploy breaks Cloud Playground ticket demos.
MOCK_TICKET_SERVICE="${GCP_MOCK_TICKET_SERVICE:-teams-mock-ticket}"
MOCK_TICKET_TOKEN_SECRET="teams-agent-mock-ticket-token"
if gcloud run services describe "${MOCK_TICKET_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1 \
  && gcloud secrets describe "${MOCK_TICKET_TOKEN_SECRET}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  MOCK_TICKET_URL="$(gcloud run services describe "${MOCK_TICKET_SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)')"
  log "偵測到 ${MOCK_TICKET_SERVICE}，重新接上 Agent ticket HTTP 與 Playground 測試 email"
  gcloud run services update "${AGENT_SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --update-env-vars="TICKET_SERVICE_MODE=HTTP,TICKET_SERVICE_BASE_URL=${MOCK_TICKET_URL}" \
    --update-secrets="TICKET_SERVICE_TOKEN=${MOCK_TICKET_TOKEN_SECRET}:latest" >/dev/null
  gcloud run services update "${ADAPTER_SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --update-env-vars="PLAYGROUND_TEST_USER_EMAIL=playground.user@example.test" >/dev/null
fi

printf '\nDeployment complete.\n'
printf 'Agent URL:   %s\n' "${AGENT_URL}"
printf 'Adapter URL: %s\n' "${ADAPTER_URL}"
printf 'Teams Developer Portal bot endpoint: %s/api/messages\n' "${ADAPTER_URL}"

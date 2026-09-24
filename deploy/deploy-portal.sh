#!/usr/bin/env bash
# Deploy Knowledge Portal to Cloud Run with GCS original dual-write.

set -Eeuo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-itr-aimasteryhub-lab}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
PORTAL_SERVICE="${GCP_PORTAL_SERVICE:-teams-knowledge-portal}"
PORTAL_SA_NAME="${GCP_PORTAL_SA:-teams-knowledge-portal}"
BACKOFFICE_SERVICE="${GCP_BACKOFFICE_API_SERVICE:-teams-ai-ops-backoffice}"
ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"
AGENT_SERVICE="${GCP_AGENT_SERVICE:-teams-rag-agent}"
CONVERTER_SERVICE="${GCP_PDF_CONVERTER_SERVICE:-teams-pdf-converter}"

PORTAL_SA="${PORTAL_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
ARTIFACT_GCS_BUCKET="${AI_OPS_ARTIFACT_GCS_BUCKET:-${PROJECT_ID}-backoffice-originals}"
RELEASE_GCS_BUCKET="${KNOWLEDGE_RELEASE_GCS_BUCKET:-${PROJECT_ID}-knowledge-releases}"
# Retained for allowed Developer API environments. BU Vertex revisions
# must not upload, inject, or mount this secret.
GOOGLE_API_SECRET="${GOOGLE_API_SECRET:-google-api-key}"
DELEGATION_SECRET="${KNOWLEDGE_DELEGATION_SECRET:-teams-agent-knowledge-delegation-secret}"
EMBEDDING_MODEL="${RAG_EMBEDDING_MODEL:-google_genai:gemini-embedding-2}"
GEMINI_API_BACKEND="VERTEX_AI"
# Explicit Vertex target only. Do not default to PROJECT_ID or "global".
VERTEX_AI_PROJECT="${VERTEX_AI_PROJECT:-}"
VERTEX_AI_CHAT_LOCATION="${VERTEX_AI_CHAT_LOCATION:-}"
VERTEX_AI_EMBEDDING_LOCATION="${VERTEX_AI_EMBEDDING_LOCATION:-}"
VERTEX_AI_PDF_LOCATION="${VERTEX_AI_PDF_LOCATION:-}"

log() { printf '[deploy-portal] %s\n' "$*"; }
fail() { printf '[deploy-portal] ERROR: %s\n' "$*" >&2; exit 1; }

command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI is required."
require_value() { [[ -n "${1:-}" ]] || fail "Missing required value: ${2}"; }

env_value() {
  local file="$1"
  local key="$2"
  awk -v target="${key}" '
    index($0, target "=") == 1 {
      sub("^[^=]*=", "")
      gsub(/\r/, "")
      print
      exit
    }
  ' "${file}"
}

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${PROJECT_DIR}/deploy/lib/vertex-revision-contract.sh"
require_explicit_vertex_project
require_approved_vertex_location "${VERTEX_AI_CHAT_LOCATION}" "VERTEX_AI_CHAT_LOCATION"
require_approved_vertex_location "${VERTEX_AI_EMBEDDING_LOCATION}" "VERTEX_AI_EMBEDDING_LOCATION"
require_approved_vertex_location "${VERTEX_AI_PDF_LOCATION}" "VERTEX_AI_PDF_LOCATION"
gcloud services enable cloudtasks.googleapis.com aiplatform.googleapis.com \
  --project="${PROJECT_ID}" >/dev/null
if ! gcloud services list --enabled --project="${PROJECT_ID}" \
  --filter="config.name=aiplatform.googleapis.com" \
  --format="value(config.name)" | grep -q aiplatform.googleapis.com; then
  fail "aiplatform.googleapis.com is not enabled on ${PROJECT_ID}."
fi
GIT_SHA="${RELEASE_GIT_SHA:-$(git -C "${PROJECT_DIR}" rev-parse --short HEAD)}"
PORTAL_IMAGE="${REGISTRY}/teams-knowledge-portal:${GIT_SHA}"
cd "${PROJECT_DIR}"

BOT_CLIENT_ID="$(env_value .env CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID)"
BOT_TENANT_ID="$(env_value .env CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID)"
BOT_CLIENT_ID="${BOT_CLIENT_ID:-$(env_value .env CLIENT_ID)}"
BOT_TENANT_ID="${BOT_TENANT_ID:-$(env_value .env TENANT_ID)}"

if ! gcloud iam service-accounts describe "${PORTAL_SA}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${PORTAL_SA_NAME}" \
    --display-name="Knowledge Portal" \
    --project="${PROJECT_ID}" >/dev/null
fi

if ! gcloud secrets describe teams-knowledge-portal-token --project="${PROJECT_ID}" >/dev/null 2>&1; then
  openssl rand -hex 24 | tr -d '\n' | gcloud secrets create teams-knowledge-portal-token \
    --replication-policy=automatic --data-file=- --project="${PROJECT_ID}" >/dev/null
fi
gcloud secrets add-iam-policy-binding teams-knowledge-portal-token \
  --member="serviceAccount:${PORTAL_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="${PROJECT_ID}" >/dev/null
gcloud projects add-iam-policy-binding "${VERTEX_AI_PROJECT}" \
  --member="serviceAccount:${PORTAL_SA}" \
  --role=roles/aiplatform.user \
  --condition=None >/dev/null
gcloud secrets add-iam-policy-binding "${DELEGATION_SECRET}" \
  --member="serviceAccount:${PORTAL_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="${PROJECT_ID}" >/dev/null

gsutil iam ch "serviceAccount:${PORTAL_SA}:roles/storage.objectAdmin" \
  "gs://${ARTIFACT_GCS_BUCKET}" >/dev/null || true
gsutil iam ch "serviceAccount:${PORTAL_SA}:roles/storage.objectCreator" \
  "gs://${RELEASE_GCS_BUCKET}" >/dev/null
gsutil iam ch "serviceAccount:${PORTAL_SA}:roles/storage.objectViewer" \
  "gs://${RELEASE_GCS_BUCKET}" >/dev/null

log "Building ${PORTAL_IMAGE}"
gcloud builds submit . \
  --project="${PROJECT_ID}" \
  --config=deploy/cloudbuild-portal.yaml \
  --substitutions="_IMAGE=${PORTAL_IMAGE}"

AGENT_URL="$(gcloud run services describe "${AGENT_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)' 2>/dev/null || true)"
ADAPTER_URL="$(gcloud run services describe "${ADAPTER_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)' 2>/dev/null || true)"
CONVERTER_URL="$(gcloud run services describe "${CONVERTER_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"

log "Deploying ${PORTAL_SERVICE}"
portal_deploy_args=(
  --project="${PROJECT_ID}"
  --region="${REGION}"
  --image="${PORTAL_IMAGE}"
  --platform=managed
  --service-account="${PORTAL_SA}"
  --no-allow-unauthenticated
  --port=8080
  --cpu=1
  --memory=2Gi
  --concurrency=8
  --min-instances=0
  --max-instances=3
  --timeout=600
  --set-env-vars="KNOWLEDGE_PORTAL_HOST=0.0.0.0,KNOWLEDGE_PORTAL_PORT=8080,KNOWLEDGE_PORTAL_DATA_DIR=/app/data,KNOWLEDGE_PORTAL_AUTH_MODE=HEADER,KNOWLEDGE_PORTAL_REQUIRE_SERVICE_TOKEN_WITH_DELEGATION=false,KNOWLEDGE_PORTAL_RELAXED_WORKFLOW=true,KNOWLEDGE_PORTAL_DEMO_MODE=true,KNOWLEDGE_PORTAL_REPOSITORY_MODE=FIRESTORE,GCP_PROJECT_ID=${PROJECT_ID},AGENT_DEPLOYMENT_ENV=poc,KNOWLEDGE_PORTAL_RELEASE_PURPOSE=PRODUCTION,RAG_EMBEDDING_MODEL=${EMBEDDING_MODEL},GEMINI_API_BACKEND=${GEMINI_API_BACKEND},VERTEX_AI_PROJECT=${VERTEX_AI_PROJECT},VERTEX_AI_CHAT_LOCATION=${VERTEX_AI_CHAT_LOCATION},VERTEX_AI_EMBEDDING_LOCATION=${VERTEX_AI_EMBEDDING_LOCATION},VERTEX_AI_PDF_LOCATION=${VERTEX_AI_PDF_LOCATION},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${VERTEX_AI_PROJECT},GOOGLE_CLOUD_LOCATION=${VERTEX_AI_EMBEDDING_LOCATION},KNOWLEDGE_PORTAL_ARTIFACT_STORAGE_BACKEND=GCS,AI_OPS_ARTIFACT_STORAGE_BACKEND=GCS,KNOWLEDGE_PORTAL_ARTIFACT_GCS_BUCKET=${ARTIFACT_GCS_BUCKET},AI_OPS_ARTIFACT_GCS_BUCKET=${ARTIFACT_GCS_BUCKET},KNOWLEDGE_PORTAL_PDF_MAX_UPLOAD_BYTES=52428800,KNOWLEDGE_PORTAL_DOCUMENT_PARSER=PDF_CONVERTER,KNOWLEDGE_PORTAL_PDF_CONVERTER_URL=${CONVERTER_URL},KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE=gemini_vision,KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE=GOOGLE_ID_TOKEN,KNOWLEDGE_PORTAL_PDF_CONVERTER_TIMEOUT_SECONDS=120,KNOWLEDGE_PORTAL_GEMINI_FILE_SEARCH_SYNC_ENABLED=false,KNOWLEDGE_PORTAL_REQUIRE_FILE_SEARCH_PARITY=false,KNOWLEDGE_PORTAL_RELEASE_GCS_BUCKET=${RELEASE_GCS_BUCKET},KNOWLEDGE_PORTAL_RELEASE_GCS_PREFIX=knowledge-releases,KNOWLEDGE_PORTAL_SOURCE_STORE_MODE=FIRESTORE,AI_OPS_SOURCE_STORE_MODE=FIRESTORE,KNOWLEDGE_PORTAL_DEFAULT_TENANT_ID=default,KNOWLEDGE_PORTAL_AGENT_API_URL=${AGENT_URL},KNOWLEDGE_PORTAL_AGENT_API_AUTH_MODE=GOOGLE_ID_TOKEN,KNOWLEDGE_PORTAL_PUBLIC_URL=https://placeholder.invalid,TEAMS_ADAPTER_URL=${ADAPTER_URL}"
  --set-secrets="KNOWLEDGE_PORTAL_TOKEN=teams-knowledge-portal-token:latest,KNOWLEDGE_PORTAL_DELEGATION_SECRET=${DELEGATION_SECRET}:latest"
)
portal_remove_secrets="$(deploy_remove_developer_api_key_secrets_args "${PORTAL_SERVICE}" || true)"
if [[ -n "${portal_remove_secrets}" ]]; then
  portal_deploy_args+=("${portal_remove_secrets}")
fi
gcloud run deploy "${PORTAL_SERVICE}" "${portal_deploy_args[@]}"
unmount_developer_api_key_secrets "${PORTAL_SERVICE}"
assert_bu_vertex_revision "${PORTAL_SERVICE}"

if cloud_run_service_exists "${CONVERTER_SERVICE}"; then
  CONVERTER_SA="$(gcloud run services describe "${CONVERTER_SERVICE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(spec.template.spec.serviceAccountName)')"
  if [[ -n "${CONVERTER_SA}" ]]; then
    gcloud projects add-iam-policy-binding "${VERTEX_AI_PROJECT}" \
      --member="serviceAccount:${CONVERTER_SA}" \
      --role=roles/aiplatform.user \
      --condition=None >/dev/null
  fi
  log "Updating ${CONVERTER_SERVICE} to VERTEX_AI without changing the image"
  converter_update_args=(
    --region="${REGION}"
    --project="${PROJECT_ID}"
    --update-env-vars="GEMINI_API_BACKEND=${GEMINI_API_BACKEND},VERTEX_AI_PROJECT=${VERTEX_AI_PROJECT},VERTEX_AI_PDF_LOCATION=${VERTEX_AI_PDF_LOCATION},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${VERTEX_AI_PROJECT},GOOGLE_CLOUD_LOCATION=${VERTEX_AI_PDF_LOCATION},PDF_CONVERTER_MODE=gemini,GEMINI_MODEL=${PDF_CONVERTER_GEMINI_MODEL:-gemini-3.8-flash}"
  )
  converter_remove_secrets="$(deploy_remove_developer_api_key_secrets_args "${CONVERTER_SERVICE}" || true)"
  if [[ -n "${converter_remove_secrets}" ]]; then
    converter_update_args+=("${converter_remove_secrets}")
  fi
  gcloud run services update "${CONVERTER_SERVICE}" "${converter_update_args[@]}" >/dev/null
  unmount_developer_api_key_secrets "${CONVERTER_SERVICE}"
  assert_bu_vertex_revision "${CONVERTER_SERVICE}"
fi

PORTAL_URL="$(gcloud run services describe "${PORTAL_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"

if ! gcloud tasks queues describe knowledge-ingestion \
  --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud tasks queues create knowledge-ingestion \
    --location="${REGION}" --project="${PROJECT_ID}" \
    --max-concurrent-dispatches=2 --max-dispatches-per-second=2 >/dev/null
fi
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${PORTAL_SA}" \
  --role=roles/cloudtasks.enqueuer \
  --condition=None >/dev/null
gcloud run services add-iam-policy-binding "${PORTAL_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --member="serviceAccount:${PORTAL_SA}" \
  --role=roles/run.invoker >/dev/null
TASK_QUEUE="projects/${PROJECT_ID}/locations/${REGION}/queues/knowledge-ingestion"
gcloud run services update "${PORTAL_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --update-env-vars="KNOWLEDGE_PORTAL_INGESTION_TASKS_QUEUE=${TASK_QUEUE},KNOWLEDGE_PORTAL_INGESTION_WORKER_URL=${PORTAL_URL},KNOWLEDGE_PORTAL_INGESTION_WORKER_SERVICE_ACCOUNT=${PORTAL_SA}" >/dev/null
unmount_developer_api_key_secrets "${PORTAL_SERVICE}"
assert_bu_vertex_revision "${PORTAL_SERVICE}"

gcloud run services add-iam-policy-binding "${AGENT_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --member="serviceAccount:${PORTAL_SA}" \
  --role=roles/run.invoker >/dev/null

gcloud run services update "${PORTAL_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --update-env-vars="KNOWLEDGE_PORTAL_PUBLIC_URL=${PORTAL_URL}" >/dev/null

# Allow Backoffice to invoke Portal
BACKOFFICE_SA="$(gcloud run services describe "${BACKOFFICE_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
if [[ -n "${BACKOFFICE_SA}" ]]; then
  gcloud run services add-iam-policy-binding "${PORTAL_SERVICE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${BACKOFFICE_SA}" \
    --role=roles/run.invoker >/dev/null
  gcloud run services update "${BACKOFFICE_SERVICE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --update-env-vars="KNOWLEDGE_PORTAL_PUBLIC_URL=${PORTAL_URL},KNOWLEDGE_PORTAL_INTERNAL_URL=${PORTAL_URL},KNOWLEDGE_PORTAL_UPSTREAM_AUTH_MODE=GOOGLE_ID_TOKEN" >/dev/null || true
fi

printf '\nPortal deployment complete.\n'
printf 'URL: %s\n' "${PORTAL_URL}"

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

PORTAL_SA="${PORTAL_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
ARTIFACT_GCS_BUCKET="${AI_OPS_ARTIFACT_GCS_BUCKET:-${PROJECT_ID}-backoffice-originals}"
RELEASE_GCS_BUCKET="${KNOWLEDGE_RELEASE_GCS_BUCKET:-${PROJECT_ID}-knowledge-releases}"
GOOGLE_API_SECRET="${GOOGLE_API_SECRET:-google-api-key}"
DELEGATION_SECRET="${KNOWLEDGE_DELEGATION_SECRET:-teams-agent-knowledge-delegation-secret}"
EMBEDDING_MODEL="${RAG_EMBEDDING_MODEL:-google_genai:gemini-embedding-2}"

log() { printf '[deploy-portal] %s\n' "$*"; }
fail() { printf '[deploy-portal] ERROR: %s\n' "$*" >&2; exit 1; }

command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI is required."

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
gcloud secrets add-iam-policy-binding "${GOOGLE_API_SECRET}" \
  --member="serviceAccount:${PORTAL_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="${PROJECT_ID}" >/dev/null
gcloud secrets add-iam-policy-binding "${DELEGATION_SECRET}" \
  --member="serviceAccount:${PORTAL_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="${PROJECT_ID}" >/dev/null

gsutil iam ch "serviceAccount:${PORTAL_SA}:roles/storage.objectAdmin" \
  "gs://${ARTIFACT_GCS_BUCKET}" >/dev/null || true
gsutil iam ch "serviceAccount:${PORTAL_SA}:roles/storage.objectCreator" \
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

log "Deploying ${PORTAL_SERVICE}"
gcloud run deploy "${PORTAL_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${PORTAL_IMAGE}" \
  --platform=managed \
  --service-account="${PORTAL_SA}" \
  --no-allow-unauthenticated \
  --port=8080 \
  --cpu=1 \
  --memory=2Gi \
  --concurrency=8 \
  --min-instances=0 \
  --max-instances=3 \
  --timeout=600 \
  --set-env-vars="KNOWLEDGE_PORTAL_HOST=0.0.0.0,KNOWLEDGE_PORTAL_PORT=8080,KNOWLEDGE_PORTAL_DATA_DIR=/app/data,KNOWLEDGE_PORTAL_AUTH_MODE=HEADER,KNOWLEDGE_PORTAL_REQUIRE_SERVICE_TOKEN_WITH_DELEGATION=false,KNOWLEDGE_PORTAL_RELAXED_WORKFLOW=true,KNOWLEDGE_PORTAL_DEMO_MODE=true,KNOWLEDGE_PORTAL_REPOSITORY_MODE=FIRESTORE,GCP_PROJECT_ID=${PROJECT_ID},AGENT_DEPLOYMENT_ENV=poc,KNOWLEDGE_PORTAL_RELEASE_PURPOSE=PRODUCTION,RAG_EMBEDDING_MODEL=${EMBEDDING_MODEL},KNOWLEDGE_PORTAL_ARTIFACT_STORAGE_BACKEND=GCS,AI_OPS_ARTIFACT_STORAGE_BACKEND=GCS,KNOWLEDGE_PORTAL_ARTIFACT_GCS_BUCKET=${ARTIFACT_GCS_BUCKET},AI_OPS_ARTIFACT_GCS_BUCKET=${ARTIFACT_GCS_BUCKET},KNOWLEDGE_PORTAL_RELEASE_GCS_BUCKET=${RELEASE_GCS_BUCKET},KNOWLEDGE_PORTAL_RELEASE_GCS_PREFIX=knowledge-releases,KNOWLEDGE_PORTAL_SOURCE_STORE_MODE=FIRESTORE,AI_OPS_SOURCE_STORE_MODE=FIRESTORE,KNOWLEDGE_PORTAL_DEFAULT_TENANT_ID=default,KNOWLEDGE_PORTAL_AGENT_API_URL=${AGENT_URL},KNOWLEDGE_PORTAL_AGENT_API_AUTH_MODE=GOOGLE_ID_TOKEN,KNOWLEDGE_PORTAL_PUBLIC_URL=https://placeholder.invalid,TEAMS_ADAPTER_URL=${ADAPTER_URL}" \
  --set-secrets="KNOWLEDGE_PORTAL_TOKEN=teams-knowledge-portal-token:latest,KNOWLEDGE_PORTAL_DELEGATION_SECRET=${DELEGATION_SECRET}:latest,GOOGLE_API_KEY=${GOOGLE_API_SECRET}:latest"

PORTAL_URL="$(gcloud run services describe "${PORTAL_SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"

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

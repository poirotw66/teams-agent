#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-itr-aimasteryhub-lab}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
MOCK_SERVICE="${GCP_MOCK_TICKET_SERVICE:-teams-mock-ticket}"
MOCK_SA_NAME="${GCP_MOCK_TICKET_SA:-teams-mock-ticket}"
AGENT_SERVICE="${GCP_AGENT_SERVICE:-teams-rag-agent}"
AGENT_SA_NAME="${GCP_AGENT_SA:-teams-rag-agent}"
ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"
MOCK_COLLECTION="${GCP_MOCK_TICKET_COLLECTION:-mock_tickets}"

MOCK_SA="${MOCK_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
AGENT_SA="${AGENT_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
MOCK_IMAGE="${REGISTRY}/${MOCK_SERVICE}:latest"
ADAPTER_IMAGE="${REGISTRY}/${ADAPTER_SERVICE}:latest"
TOKEN_SECRET="teams-agent-mock-ticket-token"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
MOCK_PUBLIC_URL="https://${MOCK_SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"

log() {
  printf '[deploy-mock-ticket] %s\n' "$*"
}

fail() {
  printf '[deploy-mock-ticket] ERROR: %s\n' "$*" >&2
  exit 1
}

cd "${PROJECT_DIR}"

command -v gcloud >/dev/null 2>&1 || fail "找不到 gcloud CLI"
command -v openssl >/dev/null 2>&1 || fail "找不到 openssl"
gcloud auth list --filter=status:ACTIVE --format='value(account)' \
  | grep -q . || fail "請先執行 gcloud auth login"

log "確認 Mock Ticket service account 與 token secret"
if ! gcloud iam service-accounts describe "${MOCK_SA}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${MOCK_SA_NAME}" \
    --display-name="Teams Mock Ticket API" \
    --project="${PROJECT_ID}" >/dev/null
fi

if ! gcloud secrets describe "${TOKEN_SECRET}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  mock_ticket_token="$(openssl rand -hex 32)"
  printf '%s' "${mock_ticket_token}" | gcloud secrets create "${TOKEN_SECRET}" \
    --replication-policy=automatic \
    --data-file=- \
    --project="${PROJECT_ID}" >/dev/null
fi

for service_account in "${MOCK_SA}" "${AGENT_SA}"; do
  gcloud secrets add-iam-policy-binding "${TOKEN_SECRET}" \
    --member="serviceAccount:${service_account}" \
    --role=roles/secretmanager.secretAccessor \
    --project="${PROJECT_ID}" >/dev/null
done
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${MOCK_SA}" \
  --role=roles/datastore.user \
  --condition=None >/dev/null

log "建置並部署 Mock Ticket API"
gcloud builds submit . \
  --config=deploy/cloudbuild-mock-ticket.yaml \
  --substitutions="_IMAGE=${MOCK_IMAGE}" \
  --project="${PROJECT_ID}"

gcloud run deploy "${MOCK_SERVICE}" \
  --image="${MOCK_IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --platform=managed \
  --service-account="${MOCK_SA}" \
  --allow-unauthenticated \
  --execution-environment=gen2 \
  --port=8080 \
  --cpu=1 \
  --memory=512Mi \
  --concurrency=20 \
  --timeout=30 \
  --min=0 \
  --max=2 \
  --set-env-vars="MOCK_TICKET_STORE_MODE=FIRESTORE,MOCK_TICKET_COLLECTION=${MOCK_COLLECTION},MOCK_TICKET_PUBLIC_BASE_URL=${MOCK_PUBLIC_URL}" \
  --set-secrets="MOCK_TICKET_TOKEN=${TOKEN_SECRET}:latest"

MOCK_URL="$(gcloud run services describe "${MOCK_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"

log "更新 Agent 連接 Mock Ticket API"
gcloud run services update "${AGENT_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --update-env-vars="TICKET_SERVICE_MODE=HTTP,TICKET_SERVICE_BASE_URL=${MOCK_URL}" \
  --update-secrets="TICKET_SERVICE_TOKEN=${TOKEN_SECRET}:latest"

log "重建 Adapter，讓 Cloud Playground 使用受限的測試 email"
gcloud builds submit . \
  --config=deploy/cloudbuild-adapter.yaml \
  --substitutions="_IMAGE=${ADAPTER_IMAGE}" \
  --project="${PROJECT_ID}"
gcloud run services update "${ADAPTER_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --image="${ADAPTER_IMAGE}" \
  --update-env-vars="PLAYGROUND_TEST_USER_EMAIL=playground.user@example.test"

printf '\nMock Ticket API deployed.\nURL: %s\n' "${MOCK_URL}"
printf 'Agent ticket mode: HTTP\n'
printf 'Data store: Firestore collection %s\n' "${MOCK_COLLECTION}"

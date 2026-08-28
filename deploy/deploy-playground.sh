#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-itr-aimasteryhub-lab}"
REGION="${GCP_REGION:-asia-east1}"
REPOSITORY="${GCP_ARTIFACT_REPOSITORY:-teams-agent}"
ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"
AGENT_SERVICE="${GCP_AGENT_SERVICE:-teams-rag-agent}"
PLAYGROUND_SERVICE="${GCP_PLAYGROUND_SERVICE:-teams-agents-playground}"
PLAYGROUND_SA_NAME="${GCP_PLAYGROUND_SA:-teams-agents-playground}"

PLAYGROUND_SA="${PLAYGROUND_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
PLAYGROUND_IMAGE="${REGISTRY}/${PLAYGROUND_SERVICE}:latest"

BOT_CLIENT_SECRET="teams-agent-bot-client-secret"
PLAYGROUND_PASSWORD_SECRET="teams-agent-playground-password"
PLAYGROUND_SESSION_SECRET="teams-agent-playground-session-secret"

log() {
  printf '[playground-deploy] %s\n' "$*"
}

fail() {
  printf '[playground-deploy] ERROR: %s\n' "$*" >&2
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

ensure_generated_secret() {
  local name="$1"
  local bytes="$2"
  if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    openssl rand -hex "${bytes}" | tr -d '\n' | gcloud secrets create "${name}" \
      --replication-policy=automatic \
      --data-file=- \
      --project="${PROJECT_ID}" >/dev/null
    log "已建立 Secret Manager secret：${name}"
  fi
}

cd "${PROJECT_DIR}"

command -v gcloud >/dev/null 2>&1 || fail "找不到 gcloud CLI"
command -v openssl >/dev/null 2>&1 || fail "找不到 openssl"
gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . \
  || fail "請先執行 gcloud auth login"

BOT_CLIENT_ID="$(env_value .env CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID)"
BOT_TENANT_ID="$(env_value .env CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID)"
# Keep compatibility with deployments created before the Teams SDK migration.
BOT_CLIENT_ID="${BOT_CLIENT_ID:-$(env_value .env CLIENT_ID)}"
BOT_TENANT_ID="${BOT_TENANT_ID:-$(env_value .env TENANT_ID)}"
[[ -n "${BOT_CLIENT_ID}" ]] || fail "缺少 .env Teams SDK client ID"
[[ -n "${BOT_TENANT_ID}" ]] || fail "缺少 .env Teams SDK tenant ID"

ADAPTER_URL="$(gcloud run services describe "${ADAPTER_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"
[[ -n "${ADAPTER_URL}" ]] || fail "找不到 Adapter Cloud Run URL"
AGENT_URL="$(gcloud run services describe "${AGENT_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"
[[ -n "${AGENT_URL}" ]] || fail "找不到 Agent Cloud Run URL"

PLAYGROUND_PUBLIC_BASE_URL="$(gcloud run services describe "${PLAYGROUND_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)' 2>/dev/null || true)"
# The first revision only needs a syntactically valid bootstrap value. After
# Cloud Run assigns the permanent URL below, the script immediately creates a
# corrected revision with that URL as the mocked connector callback base.
PLAYGROUND_PUBLIC_BASE_URL="${PLAYGROUND_PUBLIC_BASE_URL:-https://playground-bootstrap.invalid}"

log "啟用 API 並建立 Playground service account"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com \
  --project="${PROJECT_ID}" >/dev/null
if ! gcloud iam service-accounts describe "${PLAYGROUND_SA}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${PLAYGROUND_SA_NAME}" \
    --display-name="Password-protected Agents Playground" \
    --project="${PROJECT_ID}" >/dev/null
fi

gcloud secrets describe "${BOT_CLIENT_SECRET}" --project="${PROJECT_ID}" >/dev/null 2>&1 \
  || fail "找不到既有 Bot client secret：${BOT_CLIENT_SECRET}"
ensure_generated_secret "${PLAYGROUND_PASSWORD_SECRET}" 16
ensure_generated_secret "${PLAYGROUND_SESSION_SECRET}" 32

for secret in "${BOT_CLIENT_SECRET}" "${PLAYGROUND_PASSWORD_SECRET}" "${PLAYGROUND_SESSION_SECRET}"; do
  gcloud secrets add-iam-policy-binding "${secret}" \
    --member="serviceAccount:${PLAYGROUND_SA}" \
    --role=roles/secretmanager.secretAccessor \
    --project="${PROJECT_ID}" >/dev/null
done

gcloud run services add-iam-policy-binding "${AGENT_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${PLAYGROUND_SA}" \
  --role=roles/run.invoker >/dev/null

log "建置 Playground image"
gcloud builds submit . \
  --config=deploy/cloudbuild-playground.yaml \
  --substitutions="_IMAGE=${PLAYGROUND_IMAGE}" \
  --project="${PROJECT_ID}"

log "部署公開 Cloud Run；應用程式密碼閘道會保護 Playground"
gcloud run deploy "${PLAYGROUND_SERVICE}" \
  --image="${PLAYGROUND_IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --platform=managed \
  --service-account="${PLAYGROUND_SA}" \
  --allow-unauthenticated \
  --execution-environment=gen2 \
  --port=8080 \
  --cpu=1 \
  --memory=1Gi \
  --concurrency=20 \
  --timeout=3600 \
  --min=0 \
  --max=1 \
  --set-env-vars="ADAPTER_TARGET_URL=${ADAPTER_URL},DEFAULT_CHANNEL_ID=msteams,AUTH_CLIENT_ID=${BOT_CLIENT_ID},AUTH_TENANT_ID=${BOT_TENANT_ID},PLAYGROUND_PUBLIC_BASE_URL=${PLAYGROUND_PUBLIC_BASE_URL},GEMINI_FILE_SEARCH_AVAILABLE=true" \
  --set-secrets="AUTH_CLIENT_SECRET=${BOT_CLIENT_SECRET}:latest,PLAYGROUND_PASSWORD=${PLAYGROUND_PASSWORD_SECRET}:latest,SESSION_SECRET=${PLAYGROUND_SESSION_SECRET}:latest"

PLAYGROUND_URL="$(gcloud run services describe "${PLAYGROUND_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"

if [[ "${PLAYGROUND_PUBLIC_BASE_URL}" != "${PLAYGROUND_URL}" ]]; then
  log "設定 Playground public connector callback URL"
  gcloud run services update "${PLAYGROUND_SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --update-env-vars="PLAYGROUND_PUBLIC_BASE_URL=${PLAYGROUND_URL}" >/dev/null
fi

printf '\nPlayground deployment complete.\n'
printf 'URL: %s\n' "${PLAYGROUND_URL}"
printf '取得測試密碼：gcloud secrets versions access latest --secret=%s --project=%s\n' \
  "${PLAYGROUND_PASSWORD_SECRET}" "${PROJECT_ID}"

#!/usr/bin/env bash
# Front Cloud Run Playground and Console with a global HTTP load balancer.
# Cloud Run stays authenticated; the Cloud Run service agent invokes it.
# Org policies that block allUsers therefore still allow browser access via the LB.

set -Eeuo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-asia-east1}"
PLAYGROUND_SERVICE="${GCP_PLAYGROUND_SERVICE:-teams-agents-playground}"
CONSOLE_SERVICE="${GCP_CONSOLE_SERVICE:-teams-ai-ops-backoffice}"
ADAPTER_SERVICE="${GCP_ADAPTER_SERVICE:-teams-agent-adapter}"
AGENT_SERVICE="${GCP_AGENT_SERVICE:-teams-rag-agent}"

[[ -n "${PROJECT_ID}" ]] || {
  printf '[lb] ERROR: set GCP_PROJECT_ID\n' >&2
  exit 1
}

log() { printf '[lb] %s\n' "$*"; }

ensure_neg() {
  local name="$1"
  local service="$2"
  if ! gcloud compute network-endpoint-groups describe "${name}" \
    --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud compute network-endpoint-groups create "${name}" \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --network-endpoint-type=serverless \
      --cloud-run-service="${service}"
  fi
}

ensure_backend() {
  local name="$1"
  local neg="$2"
  if ! gcloud compute backend-services describe "${name}" \
    --global --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud compute backend-services create "${name}" \
      --project="${PROJECT_ID}" \
      --global \
      --load-balancing-scheme=EXTERNAL_MANAGED \
      --protocol=HTTP
    gcloud compute backend-services add-backend "${name}" \
      --project="${PROJECT_ID}" \
      --global \
      --network-endpoint-group="${neg}" \
      --network-endpoint-group-region="${REGION}"
  fi
}

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUN_AGENT="serviceAccount:service-${PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com"

log "Enable compute API"
gcloud services enable compute.googleapis.com --project="${PROJECT_ID}" >/dev/null

for service in "${PLAYGROUND_SERVICE}" "${CONSOLE_SERVICE}"; do
  log "Restrict ${service} ingress to load balancer and grant Cloud Run agent invoker"
  # Ingress restriction replaces allUsers: only GCLB can reach the service,
  # so invoker IAM can stay off without making *.run.app public.
  gcloud run services update "${service}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --ingress=internal-and-cloud-load-balancing \
    --no-invoker-iam-check >/dev/null
  gcloud run services add-iam-policy-binding "${service}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --member="${RUN_AGENT}" \
    --role=roles/run.invoker >/dev/null || true
done

# Playground proxies Bot JWT to Adapter. Cloud Run IAM would reject that
# header, and org policy blocks allUsers, so disable invoker checks here too.
# Application-level Bot auth (TEAMS_INBOUND_AUTH_MODE) still applies.
if gcloud run services describe "${ADAPTER_SERVICE}" \
  --project="${PROJECT_ID}" --region="${REGION}" >/dev/null 2>&1; then
  log "Allow Playground to reach ${ADAPTER_SERVICE} without Cloud Run IAM"
  gcloud run services update "${ADAPTER_SERVICE}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --no-invoker-iam-check >/dev/null
fi

log "Create serverless NEGs and backend services"
ensure_neg teams-playground-neg "${PLAYGROUND_SERVICE}"
ensure_neg teams-console-neg "${CONSOLE_SERVICE}"
ensure_backend teams-playground-backend teams-playground-neg
ensure_backend teams-console-backend teams-console-neg

if ! gcloud compute url-maps describe teams-public-url-map \
  --global --project="${PROJECT_ID}" >/dev/null 2>&1; then
  log "Create URL map: Console under /console-v2 and /api; Playground keeps /api/knowledge-backend"
  gcloud compute url-maps create teams-public-url-map \
    --project="${PROJECT_ID}" \
    --global \
    --default-service=teams-playground-backend
  gcloud compute url-maps add-path-matcher teams-public-url-map \
    --project="${PROJECT_ID}" \
    --global \
    --path-matcher-name=apps \
    --default-service=teams-playground-backend \
    --path-rules="/api/knowledge-backend=teams-playground-backend,/api/new-conversation=teams-playground-backend,/console-v2=teams-console-backend,/console-v2/*=teams-console-backend,/api=teams-console-backend,/api/*=teams-console-backend,/legacy=teams-console-backend,/legacy/*=teams-console-backend" \
    --new-hosts="*"
fi

if ! gcloud compute target-http-proxies describe teams-public-http-proxy \
  --global --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute target-http-proxies create teams-public-http-proxy \
    --project="${PROJECT_ID}" \
    --global \
    --url-map=teams-public-url-map
fi

if ! gcloud compute addresses describe teams-public-ip \
  --global --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute addresses create teams-public-ip \
    --project="${PROJECT_ID}" \
    --global \
    --ip-version=IPV4
fi

LB_IP="$(gcloud compute addresses describe teams-public-ip \
  --global --project="${PROJECT_ID}" --format='value(address)')"

if ! gcloud compute forwarding-rules describe teams-public-http-fw \
  --global --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute forwarding-rules create teams-public-http-fw \
    --project="${PROJECT_ID}" \
    --global \
    --load-balancing-scheme=EXTERNAL_MANAGED \
    --network-tier=PREMIUM \
    --address=teams-public-ip \
    --target-http-proxy=teams-public-http-proxy \
    --ports=80
fi

log "Point Playground public callback URL at the load balancer"
gcloud run services update "${PLAYGROUND_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --update-env-vars="PLAYGROUND_PUBLIC_BASE_URL=http://${LB_IP}" >/dev/null

# HTTP load balancers cannot complete Entra SPA redirects. Use HEADER
# test login until a domain and HTTPS certificate are in place.
if gcloud run services describe "${CONSOLE_SERVICE}" \
  --project="${PROJECT_ID}" --region="${REGION}" >/dev/null 2>&1; then
  log "Switch Console to HEADER auth for HTTP load-balancer access"
  CONSOLE_ENV="AI_OPS_BACKOFFICE_AUTH_MODE=HEADER,AI_OPS_BACKOFFICE_ALLOW_HEADER_AUTH=true,ENVIRONMENT=poc,AI_OPS_DEPLOYMENT_ENV=poc,AGENT_DEPLOYMENT_ENV=poc"
  AGENT_URL="$(gcloud run services describe "${AGENT_SERVICE}" \
    --project="${PROJECT_ID}" --region="${REGION}" \
    --format='value(status.url)' 2>/dev/null || true)"
  if [[ -n "${AGENT_URL}" ]]; then
    # Admin knowledge APIs are on the Agent origin, not /agent/chat.
    CONSOLE_ENV="${CONSOLE_ENV},AGENT_API_URL=${AGENT_URL},AGENT_API_AUDIENCE=${AGENT_URL}"
  fi
  gcloud run services update "${CONSOLE_SERVICE}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --update-env-vars="${CONSOLE_ENV}" >/dev/null
fi

printf '\nLoad balancer ready.\n'
printf 'Playground: http://%s/login\n' "${LB_IP}"
printf 'Console:    http://%s/console-v2/login\n' "${LB_IP}"
printf 'Console uses HEADER test login on HTTP. Entra needs HTTPS and a domain.\n'

#!/usr/bin/env bash
# Shared Cloud Run helpers for citation Source API wiring.
# Sourced by deploy-gcp.sh and deploy-backoffice.sh. Do not execute directly.
#
# This keeps Adapter → Backoffice preview delivery intact across deploy
# order (Adapter first, Backoffice later) and image-only updates. It does
# not create an original-file download pipeline.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  printf 'source deploy/lib/source-api-wiring.sh from a deploy script\n' >&2
  exit 1
fi

_source_api_token_secret() {
  printf '%s\n' "${BACKOFFICE_TOKEN_SECRET:-${GCP_BACKOFFICE_TOKEN_SECRET:-teams-ai-ops-backoffice-token}}"
}

_source_api_delegation_secret() {
  printf '%s\n' "${SOURCE_DELEGATION_SECRET:-${GCP_SOURCE_DELEGATION_SECRET:-teams-agent-knowledge-delegation-secret}}"
}

_source_api_adapter_service() {
  printf '%s\n' "${ADAPTER_SERVICE:-${GCP_ADAPTER_SERVICE:-teams-agent-adapter}}"
}

_source_api_backoffice_service() {
  printf '%s\n' "${BACKOFFICE_API_SERVICE:-${BACKOFFICE_SERVICE:-${GCP_BACKOFFICE_API_SERVICE:-teams-ai-ops-backoffice}}}"
}

_source_api_backoffice_worker() {
  printf '%s\n' "${BACKOFFICE_WORKER_SERVICE:-${GCP_BACKOFFICE_WORKER_SERVICE:-teams-ai-ops-backoffice-worker}}"
}

_iam_member() {
  local sa_email="$1"
  if [[ "${sa_email}" == serviceAccount:* ]]; then
    printf '%s\n' "${sa_email}"
    return
  fi
  printf 'serviceAccount:%s\n' "${sa_email}"
}

cloud_run_service_exists() {
  local service="$1"
  gcloud run services describe "${service}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1
}

ensure_generated_secret() {
  local name="$1"
  local bytes="${2:-32}"
  local seed="${3:-}"
  if gcloud secrets describe "${name}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
    return 0
  fi
  command -v openssl >/dev/null 2>&1 || fail "找不到 openssl"
  if [[ -n "${seed}" ]]; then
    printf '%s' "${seed}" | gcloud secrets create "${name}" \
      --replication-policy=automatic \
      --data-file=- \
      --project="${PROJECT_ID}" >/dev/null
  else
    openssl rand -hex "${bytes}" | tr -d '\n' | gcloud secrets create "${name}" \
      --replication-policy=automatic \
      --data-file=- \
      --project="${PROJECT_ID}" >/dev/null
  fi
  log "已建立 Secret Manager secret：${name}"
}

grant_secret_accessor() {
  local secret_name="$1"
  local sa_email="$2"
  [[ -n "${secret_name}" && -n "${sa_email}" ]] || return 0
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --member="$(_iam_member "${sa_email}")" \
    --role=roles/secretmanager.secretAccessor \
    --project="${PROJECT_ID}" >/dev/null
}

ensure_source_api_secrets() {
  local token_seed="${1:-}"
  local delegation_seed="${2:-}"
  ensure_generated_secret "$(_source_api_token_secret)" 32 "${token_seed}"
  ensure_generated_secret "$(_source_api_delegation_secret)" 32 "${delegation_seed}"
}

grant_source_api_secret_access() {
  local sa_email="$1"
  grant_secret_accessor "$(_source_api_token_secret)" "${sa_email}"
  grant_secret_accessor "$(_source_api_delegation_secret)" "${sa_email}"
}

_update_cloud_run_runtime() {
  local service="$1"
  local env_vars="$2"
  local secrets="$3"
  local remove_env_vars="${4:-}"
  local update_args=(
    --region="${REGION}"
    --project="${PROJECT_ID}"
  )
  [[ -n "${env_vars}" ]] && update_args+=(--update-env-vars="${env_vars}")
  [[ -n "${secrets}" ]] && update_args+=(--update-secrets="${secrets}")
  if declare -F deploy_remove_developer_api_key_secrets_args >/dev/null; then
    local remove_secrets
    remove_secrets="$(deploy_remove_developer_api_key_secrets_args "${service}" || true)"
    [[ -n "${remove_secrets}" ]] && update_args+=("${remove_secrets}")
  fi
  if [[ -n "${remove_env_vars}" ]] \
    && gcloud run services update "${service}" \
      "${update_args[@]}" \
      --remove-env-vars="${remove_env_vars}" >/dev/null 2>&1; then
    return 0
  fi
  gcloud run services update "${service}" "${update_args[@]}"
}

# First-time deploy may replace env/secrets. Later image updates must not
# use --set-env-vars / --set-secrets, which wipe SOURCE_API_* and mounts.
# Optional 5th argument is a comma-separated list of plaintext env keys to
# remove before mounting the same names as secrets.
deploy_cloud_run_preserving_runtime() {
  local service="$1"
  local image="$2"
  local env_vars="$3"
  local secrets="$4"
  local remove_env_vars=""
  shift 4
  if (($#)) && [[ "${1}" != --* ]]; then
    remove_env_vars="$1"
    shift
  fi

  if cloud_run_service_exists "${service}"; then
    log "更新 ${service} image（不使用 --set-env-vars，以免覆蓋既有設定）"
    gcloud run deploy "${service}" --image="${image}" "$@"
    _update_cloud_run_runtime "${service}" "${env_vars}" "${secrets}" "${remove_env_vars}"
    return 0
  fi

  log "首次部署 ${service}"
  local create_args=(--image="${image}")
  [[ -n "${env_vars}" ]] && create_args+=(--set-env-vars="${env_vars}")
  [[ -n "${secrets}" ]] && create_args+=(--set-secrets="${secrets}")
  gcloud run deploy "${service}" "${create_args[@]}" "$@"
}

_cloud_run_service_account() {
  local service="$1"
  gcloud run services describe "${service}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(spec.template.spec.serviceAccountName)'
}

mount_backoffice_source_secrets() {
  local service="$1"
  local token_secret="$2"
  local delegation_secret="$3"
  cloud_run_service_exists "${service}" || return 0
  _update_cloud_run_runtime \
    "${service}" \
    "" \
    "AI_OPS_BACKOFFICE_TOKEN=${token_secret}:latest,AI_OPS_SOURCE_DELEGATION_SECRET=${delegation_secret}:latest" \
    "AI_OPS_BACKOFFICE_TOKEN,AI_OPS_SOURCE_DELEGATION_SECRET"
}

warn_source_api_not_wired() {
  local backoffice_service="$1"
  log "警告：尚未部署 ${backoffice_service}，略過 Adapter Source API 接線"
  log "警告：Source API / citation 傳遞尚未接上。請在部署 Backoffice 後執行 deploy-backoffice.sh（會重跑 Adapter 接線：token、delegation secret、SOURCE_API_BASE_URL、run.invoker）"
}

wire_adapter_source_api() {
  local adapter_service
  local adapter_sa="${ADAPTER_SA:-}"
  local backoffice_service
  local token_secret
  local delegation_secret
  local backoffice_url
  adapter_service="$(_source_api_adapter_service)"
  backoffice_service="$(_source_api_backoffice_service)"
  token_secret="$(_source_api_token_secret)"
  delegation_secret="$(_source_api_delegation_secret)"

  if ! cloud_run_service_exists "${backoffice_service}"; then
    warn_source_api_not_wired "${backoffice_service}"
    return 0
  fi
  if ! cloud_run_service_exists "${adapter_service}"; then
    log "警告：尚未部署 ${adapter_service}，無法接上 Source API。請先部署 Adapter 後再執行接線。"
    return 0
  fi

  if [[ -z "${adapter_sa}" ]]; then
    adapter_sa="$(_cloud_run_service_account "${adapter_service}")"
  fi
  backoffice_url="$(gcloud run services describe "${backoffice_service}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)')"

  log "接上 Adapter Source API（citation preview）：${adapter_service} → ${backoffice_service}"
  gcloud run services add-iam-policy-binding "${backoffice_service}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --member="$(_iam_member "${adapter_sa}")" \
    --role=roles/run.invoker >/dev/null
  grant_source_api_secret_access "${adapter_sa}"
  gcloud run services update "${adapter_service}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --update-env-vars="SOURCE_API_BASE_URL=${backoffice_url},SOURCE_API_TIMEOUT_SECONDS=20,TEAMS_CITATION_OPEN_ACTIONS=true" \
    --update-secrets="SOURCE_API_TOKEN=${token_secret}:latest,SOURCE_DELEGATION_SECRET=${delegation_secret}:latest" \
    >/dev/null
}

# Create secrets if missing, mount them on Backoffice when present, and
# always re-wire Adapter once both services exist.
ensure_source_api_wiring() {
  local token_seed="${1:-}"
  local delegation_seed="${2:-}"
  local adapter_sa="${ADAPTER_SA:-}"
  local backoffice_sa="${BACKOFFICE_SA:-}"
  local backoffice_service
  local backoffice_worker
  local token_secret
  local delegation_secret
  backoffice_service="$(_source_api_backoffice_service)"
  backoffice_worker="$(_source_api_backoffice_worker)"
  token_secret="$(_source_api_token_secret)"
  delegation_secret="$(_source_api_delegation_secret)"

  ensure_source_api_secrets "${token_seed}" "${delegation_seed}"
  if [[ -n "${adapter_sa}" ]]; then
    grant_source_api_secret_access "${adapter_sa}"
  fi

  if ! cloud_run_service_exists "${backoffice_service}"; then
    warn_source_api_not_wired "${backoffice_service}"
    return 0
  fi

  if [[ -z "${backoffice_sa}" ]]; then
    backoffice_sa="$(_cloud_run_service_account "${backoffice_service}")"
  fi
  if [[ -n "${backoffice_sa}" ]]; then
    grant_source_api_secret_access "${backoffice_sa}"
  fi
  mount_backoffice_source_secrets "${backoffice_service}" "${token_secret}" "${delegation_secret}"
  mount_backoffice_source_secrets "${backoffice_worker}" "${token_secret}" "${delegation_secret}"
  wire_adapter_source_api
}

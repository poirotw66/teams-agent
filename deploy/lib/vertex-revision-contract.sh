#!/usr/bin/env bash
# Shared Cloud Run Vertex revision contract for BU deploy scripts.
# Sourced by deploy-gcp.sh, deploy-portal.sh, and deploy-backoffice.sh.
# --set-env-vars does not clear secret mounts. Live Developer API revisions
# keep GOOGLE_API_KEY unless it is removed explicitly.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  printf 'source deploy/lib/vertex-revision-contract.sh from a deploy script\n' >&2
  exit 1
fi

_GEMINI_DEVELOPER_API_SECRET_ENV_NAMES="GOOGLE_API_KEY GEMINI_API_KEY"
UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER="global"

vertex_field_is_blank() {
  local value
  value="$(printf '%s' "${1:-}" | tr -d '[:space:]')"
  [[ -z "${value}" ]]
}

vertex_location_is_unapproved_placeholder() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  [[ "${value}" == "${UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER}" ]]
}

require_explicit_vertex_project() {
  if vertex_field_is_blank "${VERTEX_AI_PROJECT:-}"; then
    fail "VERTEX_AI 需要顯式 VERTEX_AI_PROJECT；不得從 GCP_PROJECT_ID／project_id 推導。"
  fi
}

require_approved_vertex_location() {
  local value="${1:-}"
  local name="${2:-VERTEX location}"
  if vertex_field_is_blank "${value}"; then
    fail "VERTEX_AI 需要顯式 ${name}；不得使用空白或未核准占位 ${UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER}。"
  fi
  if vertex_location_is_unapproved_placeholder "${value}"; then
    fail "${name}=${UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER} 是 P0 未核准占位。請寫入 BU 核准的 location。"
  fi
}

if ! declare -F cloud_run_service_exists >/dev/null; then
  cloud_run_service_exists() {
    local service="$1"
    gcloud run services describe "${service}" \
      --region="${REGION}" \
      --project="${PROJECT_ID}" >/dev/null 2>&1
  }
fi

_cloud_run_container_env_json() {
  local service="$1"
  gcloud run services describe "${service}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='json(spec.template.spec.containers[0].env)'
}

cloud_run_secret_env_names() {
  local service="$1"
  _cloud_run_container_env_json "${service}" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
items = payload.get("spec", {}).get("template", {}).get("spec", {}).get("containers")
if not items:
    raise SystemExit(0)
for env in items[0].get("env") or []:
    name = (env.get("name") or "").strip()
    if not name:
        continue
    source = env.get("valueFrom") or env.get("valueSource") or {}
    if source.get("secretKeyRef"):
        print(name)
'
}

cloud_run_plain_env_value() {
  local service="$1"
  local key="$2"
  _cloud_run_container_env_json "${service}" | python3 -c '
import json
import sys

wanted = sys.argv[1]
payload = json.load(sys.stdin)
items = payload.get("spec", {}).get("template", {}).get("spec", {}).get("containers")
if not items:
    raise SystemExit(0)
for env in items[0].get("env") or []:
    if (env.get("name") or "") != wanted:
        continue
    if env.get("valueFrom") or env.get("valueSource"):
        raise SystemExit(0)
    print(env.get("value") or "")
    break
' "${key}"
}

unmount_developer_api_key_secrets() {
  local service="$1"
  cloud_run_service_exists "${service}" || return 0
  local mounted
  mounted="$(cloud_run_secret_env_names "${service}")"
  local to_remove=()
  local name
  for name in ${_GEMINI_DEVELOPER_API_SECRET_ENV_NAMES}; do
    if printf '%s\n' "${mounted}" | grep -qx "${name}"; then
      to_remove+=("${name}")
    fi
  done
  if ((${#to_remove[@]} == 0)); then
    return 0
  fi
  local joined
  joined="$(IFS=,; printf '%s' "${to_remove[*]}")"
  log "從 ${service} 卸載 Developer API secret：${joined}（保留 Secret Manager 資源）"
  gcloud run services update "${service}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --remove-secrets="${joined}" >/dev/null
}

assert_bu_vertex_revision() {
  local service="$1"
  local backend
  backend="$(cloud_run_plain_env_value "${service}" "GEMINI_API_BACKEND")"
  if [[ "${backend}" != "VERTEX_AI" ]]; then
    fail "${service} BU revision 必須是 GEMINI_API_BACKEND=VERTEX_AI，目前為 ${backend:-unset}。"
  fi
  local project
  project="$(cloud_run_plain_env_value "${service}" "VERTEX_AI_PROJECT")"
  if vertex_field_is_blank "${project}"; then
    fail "${service} BU Vertex revision 必須有顯式 VERTEX_AI_PROJECT，不得從 project_id 推導。"
  fi
  local chat_location embedding_location pdf_location
  chat_location="$(cloud_run_plain_env_value "${service}" "VERTEX_AI_CHAT_LOCATION")"
  embedding_location="$(cloud_run_plain_env_value "${service}" "VERTEX_AI_EMBEDDING_LOCATION")"
  pdf_location="$(cloud_run_plain_env_value "${service}" "VERTEX_AI_PDF_LOCATION")"
  if ! vertex_field_is_blank "${chat_location}" || ! vertex_field_is_blank "${embedding_location}"; then
    require_approved_vertex_location "${chat_location}" "${service} VERTEX_AI_CHAT_LOCATION"
    require_approved_vertex_location "${embedding_location}" "${service} VERTEX_AI_EMBEDDING_LOCATION"
  fi
  if ! vertex_field_is_blank "${pdf_location}"; then
    require_approved_vertex_location "${pdf_location}" "${service} VERTEX_AI_PDF_LOCATION"
  fi
  if vertex_field_is_blank "${chat_location}" && vertex_field_is_blank "${embedding_location}" && vertex_field_is_blank "${pdf_location}"; then
    fail "${service} BU Vertex revision 必須有核准的 VERTEX_AI_CHAT_LOCATION／EMBEDDING_LOCATION 或 VERTEX_AI_PDF_LOCATION。"
  fi
  local file_search_sync file_search_parity
  file_search_sync="$(cloud_run_plain_env_value "${service}" "KNOWLEDGE_PORTAL_GEMINI_FILE_SEARCH_SYNC_ENABLED")"
  file_search_parity="$(cloud_run_plain_env_value "${service}" "KNOWLEDGE_PORTAL_REQUIRE_FILE_SEARCH_PARITY")"
  if [[ "${file_search_sync}" == "true" || "${file_search_parity}" == "true" ]]; then
    fail "${service} BU Vertex revision 不得開啟 File Search sync／parity（選項 A）。"
  fi
  local mounted
  mounted="$(cloud_run_secret_env_names "${service}")"
  local name
  for name in ${_GEMINI_DEVELOPER_API_SECRET_ENV_NAMES}; do
    if printf '%s\n' "${mounted}" | grep -qx "${name}"; then
      fail "${service} BU Vertex revision 仍掛載 ${name}。必須先卸載，且不得刪除 Secret Manager 資源。"
    fi
    local plain
    plain="$(cloud_run_plain_env_value "${service}" "${name}")"
    if [[ -n "${plain}" ]]; then
      fail "${service} BU Vertex revision 仍有明文 ${name}。不得注入 Gemini／Google API key。"
    fi
  done
  log "${service} Vertex 契約通過：GEMINI_API_BACKEND=VERTEX_AI，無 Gemini／Google API key。"
}

deploy_remove_developer_api_key_secrets_args() {
  local service="$1"
  local mounted=""
  if cloud_run_service_exists "${service}"; then
    mounted="$(cloud_run_secret_env_names "${service}")"
  fi
  local to_remove=()
  local name
  for name in ${_GEMINI_DEVELOPER_API_SECRET_ENV_NAMES}; do
    if printf '%s\n' "${mounted}" | grep -qx "${name}"; then
      to_remove+=("${name}")
    fi
  done
  if ((${#to_remove[@]} == 0)); then
    return 0
  fi
  local joined
  joined="$(IFS=,; printf '%s' "${to_remove[*]}")"
  printf '%s' "--remove-secrets=${joined}"
}

# Live PORTAL / FOLLOW_CLOUD Agent revisions own these keys. Script defaults
# (AUTO, release-19072ac9a1e2, gemini-2.5-flash) must not replace them.
_AGENT_LIVE_KNOWLEDGE_ENV_KEYS="KNOWLEDGE_RELEASE_MODE KNOWLEDGE_ACTIVE_RELEASE_ID KNOWLEDGE_RELEASE_SELECTION_MODE GEMINI_FILE_SEARCH_STORE GEMINI_FILE_SEARCH_MODEL GEMINI_FILE_SEARCH_ENFORCE_ACL RAG_REQUIRE_FILE_SEARCH_ACL"

preserve_live_agent_knowledge_env() {
  local service="$1"
  cloud_run_service_exists "${service}" || return 0
  local key live
  log "保留 ${service} 既有 knowledge env（PORTAL／release pointer／File Search），不以腳本預設覆蓋"
  for key in ${_AGENT_LIVE_KNOWLEDGE_ENV_KEYS}; do
    live="$(cloud_run_plain_env_value "${service}" "${key}")"
    if [[ -n "${live}" ]]; then
      printf -v "${key}" '%s' "${live}"
    fi
  done
  live="$(cloud_run_plain_env_value "${service}" "KNOWLEDGE_RELEASE_GCS_BUCKET")"
  if [[ -n "${live}" ]]; then
    export KNOWLEDGE_RELEASE_BUCKET="${live}"
  fi
  live="$(cloud_run_plain_env_value "${service}" "KNOWLEDGE_RELEASE_GCS_PREFIX")"
  if [[ -n "${live}" ]]; then
    export KNOWLEDGE_RELEASE_PREFIX="${live}"
  fi
  live="$(cloud_run_plain_env_value "${service}" "KNOWLEDGE_RELEASE_TENANT_ID")"
  if [[ -n "${live}" ]]; then
    export KNOWLEDGE_RELEASE_TENANT_ID="${live}"
  fi
}

assert_bu_agent_knowledge_runtime() {
  local service="$1"
  local mode
  mode="$(cloud_run_plain_env_value "${service}" "KNOWLEDGE_SERVICE_MODE")"
  if [[ "${mode}" != "HYBRID" ]]; then
    fail "${service} BU revision 必須是 KNOWLEDGE_SERVICE_MODE=HYBRID，目前為 ${mode:-unset}。"
  fi
  log "${service} knowledge 契約通過：KNOWLEDGE_SERVICE_MODE=HYBRID。"
}

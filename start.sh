#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AGENT_SERVICE_DIR="${PROJECT_DIR}/agent_service"
PLAYGROUND_SERVICE_DIR="${PROJECT_DIR}/playground_service"

TEAMS_PORT="${PORT:-3978}"
RAG_PORT="${RAG_PORT:-8000}"
MOCK_TICKET_PORT="${MOCK_TICKET_PORT:-8090}"
PORTAL_PORT="${KNOWLEDGE_PORTAL_PORT:-8091}"
AI_OPS_PORT="${AI_OPS_BACKOFFICE_PORT:-8092}"
PLAYGROUND_PORT="${PLAYGROUND_PORT:-3979}"
PLAYGROUND_INTERNAL_PORT="${PLAYGROUND_INTERNAL_PORT:-56150}"

START_MOCK_TICKET="${START_MOCK_TICKET:-true}"
START_PORTAL="${START_PORTAL:-true}"
START_BACKOFFICE="${START_AI_OPS_BACKOFFICE:-true}"
START_PLAYGROUND="${START_PLAYGROUND:-true}"
START_TUNNEL="${START_TUNNEL:-false}"
OPEN_PLAYGROUND="${OPEN_PLAYGROUND:-true}"
OPEN_BACKOFFICE="${OPEN_BACKOFFICE:-true}"
AUTO_STOP_EXISTING="${AUTO_STOP_EXISTING:-true}"
# Consolidation M1: backoffice BFF talks to Portal as an internal dependency.
# Users only open 8092; 8091 stays loopback-only and is not a product entry.
KNOWLEDGE_BRIDGE_ENABLED="${AI_OPS_KNOWLEDGE_BRIDGE_ENABLED:-true}"
KNOWLEDGE_DELEGATION_SECRET="${KNOWLEDGE_PORTAL_DELEGATION_SECRET:-${AI_OPS_KNOWLEDGE_DELEGATION_SECRET:-local-dev-knowledge-delegation}}"
PORTAL_STATE_PATH="${KNOWLEDGE_PORTAL_STATE_PATH:-${PROJECT_DIR}/data/portal_state/portal_state.json}"
PORTAL_RELEASE_DIR="${KNOWLEDGE_PORTAL_RELEASE_DIR:-${PROJECT_DIR}/data/releases}"
PORTAL_BIND_HOST="${KNOWLEDGE_PORTAL_HOST:-127.0.0.1}"
PLAYGROUND_TEST_USER_EMAIL="${PLAYGROUND_TEST_USER_EMAIL:-playground.user@example.test}"
PLAYGROUND_PASSWORD_VALUE="${PLAYGROUND_PASSWORD:-local-playground}"
PLAYGROUND_PASSWORD_IS_DEFAULT="false"
if [[ -z "${PLAYGROUND_PASSWORD:-}" ]]; then
  PLAYGROUND_PASSWORD_IS_DEFAULT="true"
fi
PUBLIC_OPS_URL="http://127.0.0.1:${AI_OPS_PORT}"
export PORTAL_INTERNAL_URL="http://${PORTAL_BIND_HOST}:${PORTAL_PORT}"
# Prefer 127.0.0.1 in printed URLs even if bind host is localhost.
PORTAL_INTERNAL_PRINT_URL="http://127.0.0.1:${PORTAL_PORT}"

# Keep local Playground aligned with the deployed Gemini File Search setup
# without putting a key in this repository. These are the same project, secret
# and store defaults used by deploy/deploy-gcp.sh. Every value remains
# overrideable for another environment.
GEMINI_GCP_PROJECT_ID="${GCP_PROJECT_ID:-itr-aimasteryhub-lab}"
GEMINI_API_KEY_SECRET="${GEMINI_API_KEY_SECRET:-teams-agent-google-api-key}"
GEMINI_FILE_SEARCH_DEFAULT_STORE="${GEMINI_FILE_SEARCH_DEFAULT_STORE:-fileSearchStores/helpdeskstore-1p3gu83qot1s}"
AGENTIC_RAG_MODEL_DEFAULT="${AGENTIC_RAG_MODEL_DEFAULT:-google_genai:gemini-3.5-flash-lite}"
AGENTIC_AGENT_MODEL_DEFAULT="${AGENTIC_AGENT_MODEL_DEFAULT:-google_genai:gemini-3.7-flash}"
GEMINI_FILE_SEARCH_STORE_VALUE=""
GOOGLE_API_KEY_VALUE=""
GEMINI_FILE_SEARCH_ENABLED="false"
GEMINI_FILE_SEARCH_ENFORCE_ACL_VALUE="true"
RAG_MODEL_VALUE=""
AGENT_MODEL_VALUE=""

CHILD_PIDS=()

log() {
  printf '[start] %s\n' "$*"
}

fail() {
  printf '[start] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "找不到必要指令：$1"
}

port_is_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

is_project_service_process() {
  local pid="$1"
  local command
  command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  [[ "${command}" == *"${PROJECT_DIR}"* ]] \
    && [[ "${command}" =~ (teams-agent|rag-agent|mock_ticket_service|knowledge.portal|knowledge_portal|ai-ops-backoffice|ai_ops_backoffice|agentsplayground|playground_service/server.js) ]]
}

prepare_port() {
  local name="$1"
  local port="$2"
  local pid
  local pids
  local attempt

  if ! port_is_in_use "${port}"; then
    return
  fi
  if [[ "${AUTO_STOP_EXISTING}" != "true" ]]; then
    fail "${name} port ${port} 已被占用；AUTO_STOP_EXISTING=false，因此不會自動停止。"
  fi

  pids="$(lsof -nP -t -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -n "${pids}" ]] || fail "${name} port ${port} 已被占用，但無法辨識 listener。"

  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    if ! is_project_service_process "${pid}"; then
      fail "${name} port ${port} 由非本專案程序 PID ${pid} 占用，不會自動停止。"
    fi
  done <<<"${pids}"

  log "停止舊的 ${name} listener（port ${port}）…"
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    kill -TERM "${pid}" 2>/dev/null || true
  done <<<"${pids}"

  for ((attempt = 1; attempt <= 15; attempt += 1)); do
    if ! port_is_in_use "${port}"; then
      return
    fi
    sleep 1
  done
  fail "舊的 ${name} 未在 15 秒內釋放 port ${port}。"
}

require_free_port() {
  local name="$1"
  local port="$2"
  prepare_port "${name}" "${port}"
  if port_is_in_use "${port}"; then
    fail "${name} port ${port} 仍被占用。"
  fi
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local timeout_seconds="${3:-30}"
  local attempt

  log "等待 ${name} readiness…"
  for ((attempt = 1; attempt <= timeout_seconds; attempt += 1)); do
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  fail "${name} 在 ${timeout_seconds} 秒內未就緒：${url}"
}

env_value() {
  local file="$1"
  local key="$2"
  local value
  value="$(awk -v wanted="${key}" '
    /^[[:space:]]*#/ { next }
    {
      separator = index($0, "=")
      if (separator == 0) next
      name = substr($0, 1, separator - 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
      if (name == wanted) result = substr($0, separator + 1)
    }
    END { print result }
  ' "${file}")"
  value="${value%$'\r'}"
  if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "${value}"
}

configure_gemini_file_search() {
  local configured_store
  local configured_google_api_key
  local configured_gemini_api_key
  local configured_enforce_acl
  local store_source
  local key_source=""
  local warning=""

  configured_store="$(env_value "${AGENT_SERVICE_DIR}/.env" "GEMINI_FILE_SEARCH_STORE")"
  configured_google_api_key="$(env_value "${AGENT_SERVICE_DIR}/.env" "GOOGLE_API_KEY")"
  configured_gemini_api_key="$(env_value "${AGENT_SERVICE_DIR}/.env" "GEMINI_API_KEY")"
  configured_enforce_acl="$(env_value "${AGENT_SERVICE_DIR}/.env" "GEMINI_FILE_SEARCH_ENFORCE_ACL")"

  # Shell environment wins over agent_service/.env, followed by the deployed
  # legacy store. An empty assignment deliberately falls through to the next
  # source. Keeping the source lets us distinguish a copied .env placeholder
  # from a user-configured store when selecting the ACL default below.
  if [[ -n "${GEMINI_FILE_SEARCH_STORE:-}" ]]; then
    GEMINI_FILE_SEARCH_STORE_VALUE="${GEMINI_FILE_SEARCH_STORE}"
    store_source="shell"
  elif [[ -n "${configured_store}" ]]; then
    GEMINI_FILE_SEARCH_STORE_VALUE="${configured_store}"
    store_source="agent_service/.env"
  else
    GEMINI_FILE_SEARCH_STORE_VALUE="${GEMINI_FILE_SEARCH_DEFAULT_STORE}"
    store_source="legacy fallback"
  fi
  GOOGLE_API_KEY_VALUE="${GOOGLE_API_KEY:-}"
  if [[ -n "${GOOGLE_API_KEY_VALUE}" ]]; then
    key_source="GOOGLE_API_KEY 環境變數"
  elif [[ -n "${GEMINI_API_KEY:-}" ]]; then
    GOOGLE_API_KEY_VALUE="${GEMINI_API_KEY}"
    key_source="GEMINI_API_KEY 環境變數"
  elif [[ -n "${configured_google_api_key}" ]]; then
    GOOGLE_API_KEY_VALUE="${configured_google_api_key}"
    key_source="agent_service/.env 的 GOOGLE_API_KEY"
  elif [[ -n "${configured_gemini_api_key}" ]]; then
    GOOGLE_API_KEY_VALUE="${configured_gemini_api_key}"
    key_source="agent_service/.env 的 GEMINI_API_KEY"
  fi

  if [[ -z "${GOOGLE_API_KEY_VALUE}" ]]; then
    if ! command -v gcloud >/dev/null 2>&1; then
      warning="找不到 gcloud"
    elif ! gcloud auth list --filter='status:ACTIVE' --format='value(account)' \
      2>/dev/null | awk 'NF { found = 1 } END { exit !found }'; then
      warning="尚未登入 gcloud"
    elif GOOGLE_API_KEY_VALUE="$(gcloud secrets versions access latest \
      --secret="${GEMINI_API_KEY_SECRET}" \
      --project="${GEMINI_GCP_PROJECT_ID}" 2>/dev/null)" \
      && [[ -n "${GOOGLE_API_KEY_VALUE}" ]]; then
      key_source="Secret Manager（${GEMINI_API_KEY_SECRET}）"
    else
      GOOGLE_API_KEY_VALUE=""
      warning="無法讀取 Secret Manager 的 ${GEMINI_API_KEY_SECRET}"
    fi
  fi

  if [[ -n "${GOOGLE_API_KEY_VALUE}" ]]; then
    GEMINI_FILE_SEARCH_ENABLED="true"
    if [[ -n "${GEMINI_FILE_SEARCH_ENFORCE_ACL:-}" ]]; then
      GEMINI_FILE_SEARCH_ENFORCE_ACL_VALUE="${GEMINI_FILE_SEARCH_ENFORCE_ACL}"
      log "Gemini File Search ACL 沿用 GEMINI_FILE_SEARCH_ENFORCE_ACL 環境變數。"
    elif [[ -n "${configured_enforce_acl}" && "${store_source}" != "legacy fallback" ]]; then
      GEMINI_FILE_SEARCH_ENFORCE_ACL_VALUE="${configured_enforce_acl}"
      log "Gemini File Search ACL 沿用 agent_service/.env 的明確設定。"
    elif [[ "${GEMINI_FILE_SEARCH_STORE_VALUE}" == "${GEMINI_FILE_SEARCH_DEFAULT_STORE}" \
      && "${START_TUNNEL}" != "true" ]]; then
      # This legacy shared store is also deployed with ACL filtering disabled.
      # Its document metadata predates the ACL registry, and the local
      # Playground is bound to localhost by default. A tunnel remains
      # fail-closed unless the user explicitly opts out.
      GEMINI_FILE_SEARCH_ENFORCE_ACL_VALUE="false"
      log "Gemini File Search 使用共用 legacy store；本機 Playground 預設停用 ACL metadata filter（可用 GEMINI_FILE_SEARCH_ENFORCE_ACL=true 覆寫）。"
    else
      GEMINI_FILE_SEARCH_ENFORCE_ACL_VALUE="true"
      log "Gemini File Search 預設啟用 ACL metadata filter。"
    fi
    log "Gemini File Search 已啟用（store：${GEMINI_FILE_SEARCH_STORE_VALUE}；API key 來源：${key_source}）。"
    return
  fi

  # Do not expose a selectable backend that will fail on its first request.
  # Passing an empty value also prevents python-dotenv from reintroducing a
  # store from agent_service/.env after we have determined the key is absent.
  GEMINI_FILE_SEARCH_STORE_VALUE=""
  log "警告：Gemini File Search 未啟用（${warning}）；仍會以 HYBRID 啟動。"
  log "      可設定 GOOGLE_API_KEY／GEMINI_API_KEY，或執行 gcloud auth login 並確認目前帳號具 ${GEMINI_API_KEY_SECRET} 的 Secret Manager 存取權。"
}

configure_agentic_models() {
  local configured_rag_model
  local configured_agent_model

  configured_rag_model="$(env_value "${AGENT_SERVICE_DIR}/.env" "RAG_MODEL")"
  configured_agent_model="$(env_value "${AGENT_SERVICE_DIR}/.env" "AGENT_MODEL")"
  if [[ -n "${RAG_MODEL:-}" ]]; then
    RAG_MODEL_VALUE="${RAG_MODEL}"
    log "RAG model 沿用 RAG_MODEL 環境變數。"
  elif [[ -n "${configured_rag_model}" ]]; then
    RAG_MODEL_VALUE="${configured_rag_model}"
    log "RAG model 沿用 agent_service/.env 的明確設定。"
  elif [[ "${GEMINI_FILE_SEARCH_ENABLED}" == "true" ]]; then
    RAG_MODEL_VALUE="${AGENTIC_RAG_MODEL_DEFAULT}"
    log "啟用本機 RAG Gemini model：${RAG_MODEL_VALUE}（可用 RAG_MODEL 覆寫）。"
  else
    RAG_MODEL_VALUE=""
    log "未設定 RAG model 或 Google API key；知識檢索將使用 extractive-local。"
  fi

  if [[ -n "${AGENT_MODEL:-}" ]]; then
    AGENT_MODEL_VALUE="${AGENT_MODEL}"
    log "Agent model 沿用 AGENT_MODEL 環境變數。"
  elif [[ -n "${configured_agent_model}" ]]; then
    AGENT_MODEL_VALUE="${configured_agent_model}"
    log "Agent model 沿用 agent_service/.env 的明確設定。"
  elif [[ "${GEMINI_FILE_SEARCH_ENABLED}" == "true" ]]; then
    AGENT_MODEL_VALUE="${AGENTIC_AGENT_MODEL_DEFAULT}"
    log "啟用本機 agentic Gemini model：${AGENT_MODEL_VALUE}（可用 AGENT_MODEL 覆寫）。"
  else
    AGENT_MODEL_VALUE=""
  fi
}

start_background() {
  "$@" &
  CHILD_PIDS+=("$!")
}

stop_children() {
  local pid
  trap - EXIT INT TERM
  if ((${#CHILD_PIDS[@]} == 0)); then
    return
  fi
  log "正在停止本次啟動的所有服務…"
  for pid in "${CHILD_PIDS[@]}"; do
    kill -TERM "${pid}" 2>/dev/null || true
  done
  wait "${CHILD_PIDS[@]}" 2>/dev/null || true
}

monitor_children() {
  local pid
  while true; do
    for pid in "${CHILD_PIDS[@]}"; do
      kill -0 "${pid}" 2>/dev/null \
        || fail "其中一個服務已停止，正在關閉其餘服務。"
    done
    sleep 1
  done
}

trap stop_children EXIT INT TERM

require_command uv
require_command lsof
require_command curl
require_command awk
require_command ps

[[ -f "${PROJECT_DIR}/.env" ]] \
  || fail "缺少 ${PROJECT_DIR}/.env（可先執行 cp .env.example .env）"
[[ -f "${AGENT_SERVICE_DIR}/.env" ]] \
  || fail "缺少 ${AGENT_SERVICE_DIR}/.env（可先執行 cp agent_service/.env.example agent_service/.env）"

configure_gemini_file_search
configure_agentic_models

RAG_SOURCES_DIR="${RAG_SOURCES_DIR:-${PROJECT_DIR}/data/sources}"
if [[ ! -d "${RAG_SOURCES_DIR}" ]]; then
  fail "找不到知識語料目錄 ${RAG_SOURCES_DIR}。
       本機 Playground 可先執行：cp -r data/sources.sample data/sources"
fi

require_free_port "Teams Adapter" "${TEAMS_PORT}"
require_free_port "Agent Service" "${RAG_PORT}"

if [[ "${START_MOCK_TICKET}" == "true" ]]; then
  require_free_port "Mock Ticket" "${MOCK_TICKET_PORT}"
  if [[ "${PORTAL_PORT}" == "${MOCK_TICKET_PORT}" ]]; then
    fail "Knowledge Portal port ${PORTAL_PORT} 與 Mock Ticket 衝突。整合模式請使用 KNOWLEDGE_PORTAL_PORT=8091（預設），Mock Ticket 用 8090。"
  fi
fi

if [[ "${START_PORTAL}" == "true" ]]; then
  require_free_port "Knowledge Portal (internal)" "${PORTAL_PORT}"
fi

if [[ "${START_BACKOFFICE}" == "true" ]]; then
  require_free_port "AI Ops Backoffice (public entry)" "${AI_OPS_PORT}"
  if [[ "${KNOWLEDGE_BRIDGE_ENABLED}" == "true" && -z "${KNOWLEDGE_DELEGATION_SECRET}" ]]; then
    fail "已啟用 knowledge bridge，但未設定 KNOWLEDGE_PORTAL_DELEGATION_SECRET。"
  fi
  if [[ "${KNOWLEDGE_BRIDGE_ENABLED}" == "true" && "${START_PORTAL}" != "true" ]]; then
    log "警告：knowledge bridge 已啟用，但 START_PORTAL=false；後台知識 API 會回 503，直到內部 Portal 可用。"
  fi
fi

if [[ "${START_PLAYGROUND}" == "true" ]]; then
  require_command node
  require_command npm
  require_free_port "Agents Playground gateway" "${PLAYGROUND_PORT}"
  require_free_port "Agents Playground internal" "${PLAYGROUND_INTERNAL_PORT}"
  if [[ ! -x "${PLAYGROUND_SERVICE_DIR}/node_modules/.bin/agentsplayground" ]]; then
    log "安裝 Agents Playground dependencies…"
    (cd "${PLAYGROUND_SERVICE_DIR}" && npm ci)
  fi
fi

if [[ "${START_TUNNEL}" == "true" ]]; then
  require_command devtunnel
fi

if [[ "${START_MOCK_TICKET}" == "true" ]]; then
  log "啟動 Mock Ticket Service：http://127.0.0.1:${MOCK_TICKET_PORT}"
  start_background bash -c "
    cd \"\$1\"
    MOCK_TICKET_PORT=\"\$2\" exec uv run python -m teams_agent.mock_ticket_service
  " _ "${PROJECT_DIR}" "${MOCK_TICKET_PORT}"
  wait_for_url "Mock Ticket Service" "http://127.0.0.1:${MOCK_TICKET_PORT}/healthz" 20
fi

log "啟動 LangGraph Agent Service：http://127.0.0.1:${RAG_PORT}"
agent_env=(
  "PORT=${RAG_PORT}"
  "RAG_DATA_DIR=${PROJECT_DIR}/data"
  "OPS_EVENTS_ENABLED=true"
  "OPS_STORE_MODE=FILE"
  "GEMINI_FILE_SEARCH_STORE=${GEMINI_FILE_SEARCH_STORE_VALUE}"
  "GEMINI_FILE_SEARCH_ENFORCE_ACL=${GEMINI_FILE_SEARCH_ENFORCE_ACL_VALUE}"
  "GOOGLE_API_KEY=${GOOGLE_API_KEY_VALUE}"
  "RAG_MODEL=${RAG_MODEL_VALUE}"
  "AGENT_MODEL=${AGENT_MODEL_VALUE}"
)
if [[ "${START_MOCK_TICKET}" == "true" ]]; then
  agent_env+=(
    "TICKET_SERVICE_MODE=HTTP"
    "TICKET_SERVICE_BASE_URL=http://127.0.0.1:${MOCK_TICKET_PORT}"
  )
fi
(
  cd "${AGENT_SERVICE_DIR}"
  if [[ "${GEMINI_FILE_SEARCH_ENABLED}" == "true" ]]; then
    env "${agent_env[@]}" uv run --extra spike rag-agent
  else
    env "${agent_env[@]}" uv run rag-agent
  fi
) &
CHILD_PIDS+=("$!")
wait_for_url "Agent Service" "http://127.0.0.1:${RAG_PORT}/readyz" 45

export KNOWLEDGE_PORTAL_AGENT_API_URL="http://127.0.0.1:${RAG_PORT}"
export KNOWLEDGE_PORTAL_DELEGATION_SECRET="${KNOWLEDGE_DELEGATION_SECRET}"

if [[ "${START_PORTAL}" == "true" ]]; then
  log "啟動 Knowledge Portal 內部 API（僅供 8092 bridge；請勿當產品入口）：${PORTAL_INTERNAL_PRINT_URL}/"
  (
    cd "${AGENT_SERVICE_DIR}"
    export KNOWLEDGE_PORTAL_HOST="${PORTAL_BIND_HOST}"
    export KNOWLEDGE_PORTAL_PORT="${PORTAL_PORT}"
    export KNOWLEDGE_PORTAL_REPOSITORY_MODE="${KNOWLEDGE_PORTAL_REPOSITORY_MODE:-FILE}"
    export KNOWLEDGE_PORTAL_STATE_PATH="${PORTAL_STATE_PATH}"
    export KNOWLEDGE_PORTAL_RELEASE_DIR="${PORTAL_RELEASE_DIR}"
    export KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL="${KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL:-false}"
    # Local start remains HEADER-capable for break-glass; BFF uses delegation.
    export KNOWLEDGE_PORTAL_AUTH_MODE="${KNOWLEDGE_PORTAL_AUTH_MODE:-HEADER}"
    export KNOWLEDGE_PORTAL_DEMO_MODE="${KNOWLEDGE_PORTAL_DEMO_MODE:-true}"
    exec uv run knowledge-portal
  ) &
  CHILD_PIDS+=("$!")
  wait_for_url "Knowledge Portal (internal API)" "${PORTAL_INTERNAL_PRINT_URL}/healthz" 45
fi

if [[ "${START_BACKOFFICE}" == "true" ]]; then
  log "啟動 AI 資訊客服營運後台（唯一操作入口）：${PUBLIC_OPS_URL}/"
  (
    cd "${AGENT_SERVICE_DIR}"
    export AI_OPS_BACKOFFICE_PORT="${AI_OPS_PORT}"
    # Compat only: browsers should use the backoffice origin, not open Portal UI.
    export KNOWLEDGE_PORTAL_PUBLIC_URL="${PUBLIC_OPS_URL}"
    export KNOWLEDGE_PORTAL_INTERNAL_URL="${PORTAL_INTERNAL_PRINT_URL}"
    export AI_OPS_KNOWLEDGE_INTERNAL_URL="${PORTAL_INTERNAL_PRINT_URL}"
    export KNOWLEDGE_PORTAL_TOKEN="${KNOWLEDGE_PORTAL_TOKEN:-}"
    export AI_OPS_KNOWLEDGE_DELEGATION_SECRET="${KNOWLEDGE_DELEGATION_SECRET}"
    export AI_OPS_KNOWLEDGE_BRIDGE_ENABLED="${KNOWLEDGE_BRIDGE_ENABLED}"
    export AI_OPS_DEPLOYMENT_TENANT_ID="${AI_OPS_DEPLOYMENT_TENANT_ID:-local-development}"
    export AI_OPS_BACKOFFICE_AUTH_MODE="${AI_OPS_BACKOFFICE_AUTH_MODE:-HEADER}"
    export RAG_DATA_DIR="${PROJECT_DIR}/data"
    export OPS_STORE_MODE=FILE
    export OPS_AUDIT_STORE_MODE=FILE
    export AGENT_DEPLOYMENT_ENV="${AGENT_DEPLOYMENT_ENV:-dev}"
    exec uv run ai-ops-backoffice
  ) &
  CHILD_PIDS+=("$!")
  wait_for_url "AI Ops Backoffice" "${PUBLIC_OPS_URL}/healthz" 45
fi

log "啟動 Teams Adapter：http://127.0.0.1:${TEAMS_PORT}"
start_background bash -c "
  cd \"\$1\"
  export PORT=\"\$2\"
  export AGENT_MODE=api
  export AGENT_API_URL=\"http://127.0.0.1:\$3/agent/chat\"
  export BOT_PUBLIC_BASE_URL=\"http://127.0.0.1:\$2\"
  export DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS=true
  export PLAYGROUND_TEST_USER_EMAIL=\"\$4\"
  exec uv run teams-agent
" _ "${PROJECT_DIR}" "${TEAMS_PORT}" "${RAG_PORT}" "${PLAYGROUND_TEST_USER_EMAIL}"
wait_for_url "Teams Adapter" "http://127.0.0.1:${TEAMS_PORT}/readyz" 45

if [[ "${START_PLAYGROUND}" == "true" ]]; then
  PLAYGROUND_SESSION_SECRET_VALUE="${SESSION_SECRET:-$(node -e 'process.stdout.write(require("node:crypto").randomBytes(32).toString("hex"))')}"
  PLAYGROUND_URL="http://127.0.0.1:${PLAYGROUND_PORT}"

  log "啟動自訂 Agents Playground（含知識引擎選擇器）：${PLAYGROUND_URL}"
  playground_env=(
    "PORT=${PLAYGROUND_PORT}"
    "PLAYGROUND_INTERNAL_PORT=${PLAYGROUND_INTERNAL_PORT}"
    "PLAYGROUND_PASSWORD=${PLAYGROUND_PASSWORD_VALUE}"
    "SESSION_SECRET=${PLAYGROUND_SESSION_SECRET_VALUE}"
    "BOT_ENDPOINT=http://127.0.0.1:${PLAYGROUND_PORT}/_adapter/api/messages"
    "ADAPTER_TARGET_URL=http://127.0.0.1:${TEAMS_PORT}"
    "PLAYGROUND_PUBLIC_BASE_URL=${PLAYGROUND_URL}"
    "DEFAULT_CHANNEL_ID=msteams"
  )
  (
    cd "${PLAYGROUND_SERVICE_DIR}"
    # Playground UI only knows msteams/emulator/directline/webchat; gateway still
    # rewrites outbound activities to channelId=playground for agent evaluation.
    exec env "${playground_env[@]}" node server.js
  ) &
  CHILD_PIDS+=("$!")

  wait_for_url "Agents Playground gateway" "${PLAYGROUND_URL}/healthz" 45
  wait_for_url "Agents Playground adapter proxy" "${PLAYGROUND_URL}/_adapter/api/messages" 45
  wait_for_url "Agents Playground UI" "http://127.0.0.1:${PLAYGROUND_INTERNAL_PORT}/" 45

  printf '\n[start] Agents Playground UI：%s/login\n' "${PLAYGROUND_URL}"
  printf '[start] 請使用 %s/login，不要直接開啟內部 port %s。\n' "${PLAYGROUND_URL}" "${PLAYGROUND_INTERNAL_PORT}"
  printf '[start] 請固定使用 127.0.0.1，不要混用 localhost，否則登入 cookie 會失效。\n'
  if [[ "${PLAYGROUND_PASSWORD_IS_DEFAULT}" == "true" ]]; then
    printf '[start] 本機測試密碼：%s\n' "${PLAYGROUND_PASSWORD_VALUE}"
  else
    printf '[start] 請使用 PLAYGROUND_PASSWORD 設定的密碼登入。\n'
  fi
  printf '[start] 登入後右上角可選擇 HYBRID 或 Gemini File Search。\n'
  printf '[start] log 若出現 Events recording disabled，代表 Playground 遙測已關閉，屬正常現象。\n\n'

  if [[ "${OPEN_PLAYGROUND}" == "true" ]]; then
    if command -v open >/dev/null 2>&1; then
      open "${PLAYGROUND_URL}/login" || true
    else
      log "找不到 open 指令，請手動開啟 ${PLAYGROUND_URL}/login"
    fi
  fi
fi

if [[ "${START_TUNNEL}" == "true" ]]; then
  log "啟動 Dev Tunnel：port ${TEAMS_PORT}"
  start_background devtunnel host -p "${TEAMS_PORT}" --allow-anonymous
else
  log "本機 Playground 模式，不啟動 Dev Tunnel。"
fi

printf '\n'
printf '[start] ==============================================\n'
printf '[start] 環境標籤：DEV／本機整合（HEADER auth 僅限本機）\n'
printf '[start] 唯一操作入口：%s/\n' "${PUBLIC_OPS_URL}"
if [[ "${START_BACKOFFICE}" == "true" ]]; then
  printf '[start] 知識文件庫：%s/#/knowledge_ops/knowledgePortal\n' "${PUBLIC_OPS_URL}"
  printf '[start] 知識 API：%s/api/knowledge/*（BFF → 內部 Portal）\n' "${PUBLIC_OPS_URL}"
  printf '[start] knowledge bridge：%s\n' "${KNOWLEDGE_BRIDGE_ENABLED}"
fi
if [[ "${START_PORTAL}" == "true" ]]; then
  printf '[start] Portal 程序：仍會在 %s 啟動，但僅 loopback 內部 API，請不要開瀏覽器進 8091。\n' \
    "${PORTAL_INTERNAL_PRINT_URL}"
fi
if [[ "${START_MOCK_TICKET}" == "true" ]]; then
  printf '[start] Mock Ticket：http://127.0.0.1:%s/\n' "${MOCK_TICKET_PORT}"
fi
printf '[start] Agent：http://127.0.0.1:%s/ ｜ Teams Adapter：http://127.0.0.1:%s/\n' \
  "${RAG_PORT}" "${TEAMS_PORT}"
printf '[start] ==============================================\n\n'

if [[ "${OPEN_BACKOFFICE}" == "true" && "${START_BACKOFFICE}" == "true" ]]; then
  if command -v open >/dev/null 2>&1; then
    open "${PUBLIC_OPS_URL}/" || true
  fi
fi

log "所有服務已啟動。按 Ctrl+C 可一起停止。"
monitor_children

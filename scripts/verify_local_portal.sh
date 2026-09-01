#!/usr/bin/env bash
# Local verification for Knowledge Portal + Agent release integration.
#
# Usage (from repo root):
#   ./scripts/verify_local_portal.sh
#
# Notes:
# - Portal defaults to port 8091 to avoid clashing with Mock Ticket (8090) in start.sh.
# - Agent defaults to port 8000 (same as start.sh / RAG_PORT).

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="${REPO_ROOT}/agent_service"
PORTAL_PORT="${KNOWLEDGE_PORTAL_PORT:-8091}"
AGENT_PORT="${RAG_PORT:-8000}"
RELEASE_DIR="${KNOWLEDGE_PORTAL_RELEASE_DIR:-${REPO_ROOT}/data/releases}"
STATE_PATH="${KNOWLEDGE_PORTAL_STATE_PATH:-${REPO_ROOT}/data/portal_state/portal_state.json}"

log() { printf '[verify] %s\n' "$*"; }
fail() { printf '[verify] ERROR: %s\n' "$*" >&2; exit 1; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing command: $1"
}

port_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local timeout="${3:-30}"
  local attempt
  for ((attempt = 1; attempt <= timeout; attempt += 1)); do
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  fail "${name} not ready within ${timeout}s: ${url}"
}

CHILD_PIDS=()
cleanup() {
  local pid
  for pid in "${CHILD_PIDS[@]:-}"; do
    kill -TERM "${pid}" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

require_command uv
require_command curl
require_command lsof

if [[ ! -f "${RELEASE_DIR}/active_release.json" ]]; then
  log "No active release found. Running bootstrap…"
  "${REPO_ROOT}/scripts/bootstrap_knowledge_release_0001.sh"
fi

if port_in_use "${AGENT_PORT}"; then
  log "Agent already listening on ${AGENT_PORT}; reusing existing process."
  MANAGE_AGENT=false
else
  MANAGE_AGENT=true
  log "Starting Agent on http://127.0.0.1:${AGENT_PORT} (KNOWLEDGE_RELEASE_MODE=PORTAL)…"
  (
    cd "${AGENT_DIR}"
    export PORT="${AGENT_PORT}"
    export KNOWLEDGE_RELEASE_MODE=PORTAL
    export KNOWLEDGE_RELEASE_DIR="${RELEASE_DIR}"
    export RAG_DATA_DIR="${REPO_ROOT}/data"
    export RAG_AUTO_BUILD_INDEX=false
    exec uv run rag-agent
  ) &
  CHILD_PIDS+=("$!")
  wait_for_url "Agent Service" "http://127.0.0.1:${AGENT_PORT}/readyz" 45
fi

if port_in_use "${PORTAL_PORT}"; then
  log "Portal already listening on ${PORTAL_PORT}; reusing existing process."
  MANAGE_PORTAL=false
else
  MANAGE_PORTAL=true
  log "Starting Knowledge Portal on http://127.0.0.1:${PORTAL_PORT}…"
  (
    cd "${AGENT_DIR}"
    export KNOWLEDGE_PORTAL_PORT="${PORTAL_PORT}"
    export KNOWLEDGE_PORTAL_REPOSITORY_MODE=FILE
    export KNOWLEDGE_PORTAL_STATE_PATH="${STATE_PATH}"
    export KNOWLEDGE_PORTAL_RELEASE_DIR="${RELEASE_DIR}"
    export KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL=false
    export KNOWLEDGE_PORTAL_AGENT_API_URL="http://127.0.0.1:${AGENT_PORT}"
    exec uv run knowledge-portal
  ) &
  CHILD_PIDS+=("$!")
  wait_for_url "Knowledge Portal" "http://127.0.0.1:${PORTAL_PORT}/" 45
fi

log "Checking Agent readyz…"
READYZ="$(curl --silent "http://127.0.0.1:${AGENT_PORT}/readyz")"
printf '%s\n' "${READYZ}" | grep -q '"knowledgeReleaseId":"release-0001"' \
  || fail "Agent readyz missing release-0001: ${READYZ}"
printf '%s\n' "${READYZ}" | grep -q 'portal_release' \
  || fail "Agent readyz not loading portal release: ${READYZ}"
log "Agent readyz OK (release-0001 / portal_release)."

log "Checking Agent /retrieval/search…"
SEARCH="$(curl --silent -X POST "http://127.0.0.1:${AGENT_PORT}/retrieval/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"密碼被鎖定","groups":[],"limit":3}')"
printf '%s\n' "${SEARCH}" | grep -qi 'vpn\|密碼' \
  || fail "Retrieval search returned unexpected payload: ${SEARCH}"
log "Agent retrieval OK."

log "Checking Portal dashboard…"
DASH="$(curl --silent \
  -H "X-Portal-User-Id: verify.local" \
  -H "X-Portal-User-Name: Verify Local" \
  -H "X-Portal-Role: MANAGER" \
  -H "X-Portal-Owner-Units: IT Service Desk" \
  "http://127.0.0.1:${PORTAL_PORT}/api/dashboard")"
printf '%s\n' "${DASH}" | grep -q 'release-0001' \
  || fail "Portal dashboard missing active release: ${DASH}"
log "Portal dashboard OK."

log "Checking Portal draft workflow (create + draft-search)…"
CREATE="$(curl --silent -X POST "http://127.0.0.1:${PORTAL_PORT}/api/documents" \
  -H "Content-Type: application/json" \
  -H "X-Portal-User-Id: author.local" \
  -H "X-Portal-User-Name: Author Local" \
  -H "X-Portal-Role: CONTRIBUTOR" \
  -H "X-Portal-Owner-Units: IT Service Desk" \
  -d '{
    "title":"VPN 登入問題",
    "summary":"本機驗證草稿",
    "category":"VPN",
    "owner_unit_id":"IT Service Desk",
    "business_contact":"it-helpdesk@example.test",
    "audience_type":"ALL_EMPLOYEES",
    "audience_group_ids":[],
    "effective_at":"2026-08-01",
    "review_due_at":"2026-12-01",
    "change_summary":"Local verify",
    "change_reason":"Local verify draft search",
    "markdown_content":"# VPN 登入問題\n\n## 正文\n\n請確認帳號未鎖定。"
  }')"
DOC_ID="$(printf '%s' "${CREATE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["document"]["document_id"])')"
DRAFT="$(curl --silent -X POST "http://127.0.0.1:${PORTAL_PORT}/api/documents/${DOC_ID}/draft-search" \
  -H "Content-Type: application/json" \
  -H "X-Portal-User-Id: author.local" \
  -H "X-Portal-User-Name: Author Local" \
  -H "X-Portal-Role: CONTRIBUTOR" \
  -H "X-Portal-Owner-Units: IT Service Desk" \
  -d '{"query":"請確認帳號未鎖定","groups":[],"limit":4}')"
printf '%s\n' "${DRAFT}" | grep -q '"matchedDraft":true' \
  || fail "Draft search did not match draft: ${DRAFT}"
log "Portal draft-search OK."

printf '\n[verify] Local checks passed.\n'
printf '[verify] Portal UI:  http://127.0.0.1:%s/\n' "${PORTAL_PORT}"
printf '[verify] Agent readyz: http://127.0.0.1:%s/readyz\n' "${AGENT_PORT}"
printf '[verify] Playground (optional): ./start.sh then ask "VPN 密碼鎖住怎麼辦"\n'
if [[ "${MANAGE_AGENT:-false}" == "true" || "${MANAGE_PORTAL:-false}" == "true" ]]; then
  printf '[verify] This script started temporary services; they stop when the script exits.\n'
  printf '[verify] To keep them running, start manually in separate terminals.\n'
fi

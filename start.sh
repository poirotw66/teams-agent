#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AGENT_SERVICE_DIR="${PROJECT_DIR}/agent_service"
TEAMS_PORT="${PORT:-3978}"
RAG_PORT="${RAG_PORT:-8000}"
START_TUNNEL="${START_TUNNEL:-true}"
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

stop_children() {
  local pid
  trap - EXIT INT TERM
  if ((${#CHILD_PIDS[@]} > 0)); then
    log "正在停止本次啟動的服務…"
    for pid in "${CHILD_PIDS[@]}"; do
      kill -TERM "${pid}" 2>/dev/null || true
    done
    wait "${CHILD_PIDS[@]}" 2>/dev/null || true
  fi
}

trap stop_children EXIT INT TERM

require_command uv
require_command lsof
require_command curl

[[ -f "${PROJECT_DIR}/.env" ]] \
  || fail "缺少 ${PROJECT_DIR}/.env"
[[ -f "${AGENT_SERVICE_DIR}/.env" ]] \
  || fail "缺少 ${AGENT_SERVICE_DIR}/.env"

port_is_in_use "${TEAMS_PORT}" \
  && fail "Teams Adapter port ${TEAMS_PORT} 已被占用，請先停止舊的 uv run teams-agent。"
port_is_in_use "${RAG_PORT}" \
  && fail "Agent Service port ${RAG_PORT} 已被占用，請先停止舊的 uv run rag-agent。"

if [[ "${START_TUNNEL}" == "true" ]]; then
  require_command devtunnel
fi

log "啟動 LangGraph Agent Service：http://localhost:${RAG_PORT}"
(
  cd "${AGENT_SERVICE_DIR}"
  PORT="${RAG_PORT}" exec uv run rag-agent
) &
CHILD_PIDS+=("$!")

log "等待 Agent Service readiness…"
for _ in {1..30}; do
  if curl --fail --silent "http://localhost:${RAG_PORT}/readyz" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent "http://localhost:${RAG_PORT}/readyz" >/dev/null \
  || fail "Agent Service 在 30 秒內未就緒。"

log "啟動 Teams Adapter：http://localhost:${TEAMS_PORT}"
(
  cd "${PROJECT_DIR}"
  PORT="${TEAMS_PORT}" exec uv run teams-agent
) &
CHILD_PIDS+=("$!")

log "等待 Teams Adapter readiness…"
for _ in {1..30}; do
  if curl --fail --silent "http://localhost:${TEAMS_PORT}/readyz" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent "http://localhost:${TEAMS_PORT}/readyz" >/dev/null \
  || fail "Teams Adapter 在 30 秒內未就緒。"

if [[ "${START_TUNNEL}" == "true" ]]; then
  log "啟動 Dev Tunnel：port ${TEAMS_PORT}"
  devtunnel host -p "${TEAMS_PORT}" --allow-anonymous &
  CHILD_PIDS+=("$!")
else
  log "START_TUNNEL=false，略過 Dev Tunnel。"
fi

log "全部服務已啟動。按 Ctrl+C 可一起停止。"
while true; do
  for pid in "${CHILD_PIDS[@]}"; do
    kill -0 "${pid}" 2>/dev/null \
      || fail "其中一個服務已停止，正在關閉其餘服務。"
  done
  sleep 1
done

#!/usr/bin/env bash
# Sync existing local knowledge (data/sources + data/index/chunks.json) into portal.
#
# Usage (from repo root):
#   ./scripts/sync_local_knowledge.sh [--reindex]

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

export KNOWLEDGE_PORTAL_REPOSITORY_MODE="${KNOWLEDGE_PORTAL_REPOSITORY_MODE:-FILE}"
export KNOWLEDGE_PORTAL_STATE_PATH="${KNOWLEDGE_PORTAL_STATE_PATH:-${REPO_ROOT}/data/portal_state/portal_state.json}"
export KNOWLEDGE_PORTAL_RELEASE_DIR="${KNOWLEDGE_PORTAL_RELEASE_DIR:-${REPO_ROOT}/data/releases}"
export KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL="${KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL:-false}"

cd "${REPO_ROOT}/agent_service"
uv run python "${REPO_ROOT}/scripts/sync_local_knowledge.py" "$@"

printf '\nNext steps:\n'
printf '  1. Portal UI:  cd agent_service && KNOWLEDGE_PORTAL_PORT=8091 uv run knowledge-portal\n'
printf '  2. Agent/Playground: KNOWLEDGE_RELEASE_MODE=AUTO ./start.sh\n'
printf '     (AUTO prefers portal release when active; falls back to bundled index)\n'

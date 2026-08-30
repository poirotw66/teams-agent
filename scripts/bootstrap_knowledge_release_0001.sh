#!/usr/bin/env bash
# Import existing Markdown sources into portal state and activate release-0001.
#
# Usage (from repo root):
#   ./scripts/bootstrap_knowledge_release_0001.sh [sources-dir]

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

export KNOWLEDGE_PORTAL_REPOSITORY_MODE="${KNOWLEDGE_PORTAL_REPOSITORY_MODE:-FILE}"
export KNOWLEDGE_PORTAL_STATE_PATH="${KNOWLEDGE_PORTAL_STATE_PATH:-${REPO_ROOT}/data/portal_state/portal_state.json}"
export KNOWLEDGE_PORTAL_RELEASE_DIR="${KNOWLEDGE_PORTAL_RELEASE_DIR:-${REPO_ROOT}/data/releases}"
export KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL="${KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL:-false}"

cd "${REPO_ROOT}/agent_service"
uv run python "${REPO_ROOT}/scripts/bootstrap_knowledge_release_0001.py" "${1:-}"

printf '\nNext steps:\n'
printf '  1. Start portal:  cd agent_service && uv run knowledge-portal\n'
printf '  2. Start agent:   KNOWLEDGE_RELEASE_MODE=PORTAL uv run rag-agent\n'
printf '  3. Verify:        curl -s http://localhost:8000/readyz | jq .knowledgeReleaseId\n'

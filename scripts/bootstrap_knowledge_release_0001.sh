#!/usr/bin/env bash
# Backward-compatible alias: sync local knowledge into portal release-0001.
#
# Usage (from repo root):
#   ./scripts/bootstrap_knowledge_release_0001.sh [sources-dir]

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${REPO_ROOT}/scripts/sync_local_knowledge.sh" "$@"

#!/usr/bin/env bash
# Capture a redacted terraform plan for handoff evidence.
#
# Usage (from repo root):
#   ./infra/scripts/terraform-plan-evidence.sh [backend-config] [output-file]
#
# Example (POC import verification):
#   ./infra/scripts/terraform-plan-evidence.sh infra/environments/poc/backend.hcl handoff-plan-evidence.txt

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TERRAFORM_DIR="${REPO_ROOT}/infra/terraform"
BACKEND_CONFIG="${1:-${REPO_ROOT}/infra/environments/poc/backend.hcl}"
OUTPUT_FILE="${2:-${REPO_ROOT}/handoff-plan-evidence.txt}"

cd "${TERRAFORM_DIR}"

command -v terraform >/dev/null 2>&1 || { echo "terraform not found" >&2; exit 1; }

terraform init -backend-config="${BACKEND_CONFIG}" -input=false >/dev/null

PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/tfplan.XXXXXX")"
trap 'rm -f "${PLAN_FILE}"' EXIT

terraform plan -input=false -no-color -out="${PLAN_FILE}"
terraform show -no-color "${PLAN_FILE}" \
  | sed -E \
    -e 's/(client_id[[:space:]]*=[[:space:]]*")[^"]*/\1<redacted>/g' \
    -e 's/(tenant_id[[:space:]]*=[[:space:]]*")[^"]*/\1<redacted>/g' \
    -e 's/(bot_client_id[[:space:]]*=[[:space:]]*")[^"]*/\1<redacted>/g' \
    -e 's/(bot_tenant_id[[:space:]]*=[[:space:]]*")[^"]*/\1<redacted>/g' \
    -e 's/(GOOGLE_API_KEY[[:space:]]*=[[:space:]]*")[^"]*/\1<redacted>/g' \
    -e 's/(CLIENT_SECRET[[:space:]]*=[[:space:]]*")[^"]*/\1<redacted>/g' \
  > "${OUTPUT_FILE}"

printf 'Wrote redacted plan evidence to %s\n' "${OUTPUT_FILE}"

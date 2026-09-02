#!/usr/bin/env bash
# Capture a redacted terraform plan for handoff evidence.
#
# Usage (from repo root):
#   ./infra/scripts/terraform-plan-evidence.sh [backend-config] [output-file]
#
# Example (POC import verification):
#   ./infra/scripts/terraform-plan-evidence.sh infra/environments/poc/backend.hcl artifacts/terraform-plan-evidence.txt

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TERRAFORM_DIR="${REPO_ROOT}/infra/terraform"
BACKEND_CONFIG="${REPO_ROOT}/infra/environments/poc/backend.hcl"
OUTPUT_FILE="${REPO_ROOT}/artifacts/terraform-plan-evidence.txt"
if [[ $# -gt 0 ]]; then
  if [[ "$1" = /* ]]; then
    BACKEND_CONFIG="$1"
  else
    BACKEND_CONFIG="${REPO_ROOT}/$1"
  fi
  shift
fi
if [[ $# -gt 0 ]]; then
  if [[ "$1" = /* ]]; then
    OUTPUT_FILE="$1"
  else
    OUTPUT_FILE="${REPO_ROOT}/$1"
  fi
  shift
fi

cd "${TERRAFORM_DIR}"

command -v terraform >/dev/null 2>&1 || { echo "terraform not found" >&2; exit 1; }

terraform init -backend-config="${BACKEND_CONFIG}" -input=false >/dev/null

PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/tfplan.XXXXXX")"
trap 'rm -f "${PLAN_FILE}"' EXIT

terraform plan -input=false -no-color -out="${PLAN_FILE}" \
  -var-file="${REPO_ROOT}/infra/environments/poc/terraform.tfvars.example" \
  -var='bot_client_id=11111111-1111-1111-1111-111111111111' \
  -var='bot_tenant_id=22222222-2222-2222-2222-222222222222'
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

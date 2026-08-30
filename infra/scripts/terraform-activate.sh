#!/usr/bin/env bash
# Activate Services: Cloud Run Agent/Adapter, Cloud Run IAM, runtime env, and
# secret references. Requires pinned images and secret versions.
#
# Usage (from repo root):
#   ./infra/scripts/terraform-activate.sh [backend-config]
#
# Set agent_image and adapter_image in terraform.tfvars before running.

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TERRAFORM_DIR="${REPO_ROOT}/infra/terraform"
BACKEND_CONFIG="${REPO_ROOT}/infra/environments/test/backend.hcl"
if [[ $# -gt 0 ]]; then
  BACKEND_CONFIG="$1"
  shift
fi

cd "${TERRAFORM_DIR}"

command -v terraform >/dev/null 2>&1 || { echo "terraform not found" >&2; exit 1; }

terraform init -backend-config="${BACKEND_CONFIG}" -input=false
terraform apply -input=false -var="deployment_phase=activate" "$@"

printf '\nActivate complete. Next:\n'
printf '  1. Set adapter_public_base_url in terraform.tfvars if needed\n'
printf '  2. terraform apply -var="deployment_phase=activate" (or re-run this script)\n'
printf '%s\n' '  3. curl "$(terraform output -raw adapter_url)/readyz"'
